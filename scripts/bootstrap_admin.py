# scripts/bootstrap_admin.py
import os
import sys
from datetime import datetime

from dotenv import load_dotenv, set_key
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)
# --- End Path Adjustment ---

from projectdavid_common import \
    UtilsInterface
from projectdavid_common.utilities.logging_service import \
    LoggingUtility


from entities_api.models.models import (
    ApiKey, User)


dotenv_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path=dotenv_path)
DATABASE_URL = os.getenv("SPECIAL_DB_URL")
if not DATABASE_URL:
    print("Error: DATABASE_URL environment variable not set.")
    sys.exit(1)

# Configure Admin User Details (Customize as needed)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_FULL_NAME = "Default Admin"
ADMIN_KEY_NAME = "Admin Bootstrap Key"

# --- Output File Configuration ---
CREDENTIALS_FILENAME = "admin_credentials.txt"
CREDENTIALS_FILE_PATH = os.path.join(project_root, CREDENTIALS_FILENAME)
# --- End Output File Configuration ---

# --- Setup ---
logging_utility = LoggingUtility()
identifier_service = UtilsInterface.IdentifierService()  # Get instance

# --- Database Connection ---
try:
    engine = create_engine(DATABASE_URL, echo=False)  # echo=False for less noise
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logging_utility.info("Database engine created.")
    # Ensure you have run migrations or create_all appropriately elsewhere
except Exception as e:
    logging_utility.error(f"Failed to connect to database: {e}", exc_info=True)
    sys.exit(1)


def bootstrap_admin_user():
    """
    Creates the initial admin user and their API key if they don't exist.
    Writes the generated key details to admin_credentials.txt and appends/updates
    them in the .env file located at the project root.
    """
    db = SessionLocal()
    admin_user = None
    plain_text_api_key = None
    key_prefix = None
    generated_key_in_this_run = False

    try:
        logging_utility.info(f"Checking for existing admin user: {ADMIN_EMAIL}")
        admin_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()

        if admin_user:
            logging_utility.warning(
                f"Admin user '{ADMIN_EMAIL}' already exists (ID: {admin_user.id})."
            )
            existing_key = (
                db.query(ApiKey).filter(ApiKey.user_id == admin_user.id).first()
            )
            if existing_key:
                logging_utility.info(
                    f"Existing admin user already has an API key (Prefix: {existing_key.prefix}). No action needed."
                )
                return  # Exit if user and key exist
            else:
                logging_utility.warning(
                    f"Existing admin user {admin_user.id} has NO API key. Generating one now."
                )
                # User object is already loaded
        else:
            # --- Create New Admin User ---
            logging_utility.info(f"Creating new admin user: {ADMIN_EMAIL}")
            admin_user_id = identifier_service.generate_user_id()
            admin_user = User(
                id=admin_user_id,
                email=ADMIN_EMAIL,
                full_name=ADMIN_FULL_NAME,
                email_verified=True,
                oauth_provider="local",
                is_admin=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(admin_user)
            logging_utility.info(f"Admin user object created with ID: {admin_user.id}")
            db.commit()
            db.refresh(admin_user)
            logging_utility.info("Admin user committed to database.")

        # --- If we reached here, we need to generate and store an API Key ---
        generated_key_in_this_run = True
        logging_utility.info(f"Generating API key for admin user: {admin_user.id}")

        # 1. Generate the plain text key
        plain_text_api_key = ApiKey.generate_key(prefix="ad_")
        key_prefix = plain_text_api_key[:8]

        # 2. Hash the key
        hashed_key = ApiKey.hash_key(plain_text_api_key)

        # 3. Create the ApiKey DB record
        api_key_record = ApiKey(
            user_id=admin_user.id,
            key_name=ADMIN_KEY_NAME,
            hashed_key=hashed_key,
            prefix=key_prefix,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db.add(api_key_record)
        logging_utility.info(f"API Key record created (Prefix: {key_prefix})")

        # 4. Commit the API Key
        db.commit()
        logging_utility.info("API Key record committed to database.")

        # --- Write/Append details IF a key was generated in this run ---
        if generated_key_in_this_run and plain_text_api_key and admin_user:

            # --- Write details to text file (as before) ---
            logging_utility.info(
                f"Attempting to write credentials to: {CREDENTIALS_FILE_PATH}"
            )
            try:
                # Prepare the content for the file
                file_content = (
                    f"# Admin Credentials Generated: {datetime.utcnow().isoformat()}Z\n"
                    f"ADMIN_USER_EMAIL={admin_user.email}\n"
                    f"ADMIN_USER_ID={admin_user.id}\n"
                    f"ADMIN_KEY_PREFIX={key_prefix}\n"
                    f"ADMIN_API_KEY={plain_text_api_key}\n"
                )
                # Write/overwrite the file
                with open(CREDENTIALS_FILE_PATH, "w") as f:
                    f.write(file_content)
                logging_utility.info(
                    f"Successfully wrote credentials to: {CREDENTIALS_FILE_PATH}"
                )
                print(f"\nInfo: Admin credentials written to: {CREDENTIALS_FILE_PATH}")
            except Exception as file_err:
                logging_utility.error(
                    f"Failed to write credentials file: {file_err}", exc_info=True
                )
                print(
                    f"\nWarning: Failed to write credentials file at {CREDENTIALS_FILE_PATH}: {file_err}"
                )
                # Continue, as we still want to try writing to .env and print to console

            # --- Append/Update details in .env file ---
            logging_utility.info(f"Attempting to update .env file at: {dotenv_path}")
            try:

                # It will create the file if it doesn't exist.
                # Note: Ensure correct permissions for the script to write to .env
                set_key(dotenv_path, "ADMIN_USER_EMAIL", admin_user.email)
                set_key(
                    dotenv_path, "ADMIN_USER_ID", str(admin_user.id)
                )  # Ensure ID is string
                set_key(dotenv_path, "ADMIN_KEY_PREFIX", key_prefix)
                set_key(dotenv_path, "ENTITIES_API_KEY", plain_text_api_key)
                logging_utility.info(f"Successfully updated .env file: {dotenv_path}")
                print(f"Info: Admin credentials also updated in: {dotenv_path}")
                # Add a reminder about gitignore
                print(
                    f"Info: Ensure '{os.path.basename(dotenv_path)}' and '{CREDENTIALS_FILENAME}' are in your .gitignore file!"
                )

            except Exception as dotenv_err:
                logging_utility.error(
                    f"Failed to update .env file: {dotenv_err}", exc_info=True
                )
                print(
                    f"\nWarning: Failed to update .env file at {dotenv_path}: {dotenv_err}"
                )


            # --- IMPORTANT: Output the Plain Text Key to Console ---
            print("\n" + "=" * 60)
            print("  IMPORTANT: Admin API Key Generated!")
            print(f"  User Email: {admin_user.email}")
            print(f"  User ID:    {admin_user.id}")
            print(f"  Key Prefix: {key_prefix}")
            print("-" * 60)
            print(f"  PLAIN TEXT API KEY: {plain_text_api_key}")
            print("-" * 60)
            print(f"  Store this key securely. Details also saved/updated in:")
            print(f"  {CREDENTIALS_FILE_PATH}")
            print(f"  {dotenv_path}")
            print("=" * 60 + "\n")
        # --- End write/append details ---

    except Exception as e:
        logging_utility.error(
            f"An error occurred during admin bootstrap: {e}", exc_info=True
        )
        if db.is_active:  # Check if rollback is possible
            db.rollback()
        print(f"\nError: Failed to bootstrap admin user. Check logs. Error: {e}\n")
    finally:
        if db:
            db.close()
            logging_utility.info("Database session closed.")


if __name__ == "__main__":
    print("Starting admin user bootstrap process...")
    # Ensure .env path is determined correctly before starting
    if not os.path.exists(dotenv_path):
        print(f"Info: .env file not found at '{dotenv_path}'. It will be created.")
    elif not os.access(dotenv_path, os.W_OK):
        print(
            f"Warning: Script may not have write permissions for '{dotenv_path}'. .env update might fail."
        )

    if not os.access(os.path.dirname(CREDENTIALS_FILE_PATH), os.W_OK):
        print(
            f"Warning: Script may not have write permissions for the directory '{os.path.dirname(CREDENTIALS_FILE_PATH)}'. File writing might fail."
        )

    bootstrap_admin_user()
    print("Bootstrap process finished.")
