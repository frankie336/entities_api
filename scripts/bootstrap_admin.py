# scripts/bootstrap_admin.py
#
import argparse
import os
import sys
from datetime import datetime

# Use find_dotenv to locate .env reliably, especially if script is run from different depths
from dotenv import find_dotenv, load_dotenv, set_key
from sqlalchemy import create_engine
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy.orm import Session, sessionmaker

# --- Path Adjustment (Ensure project root is found) ---
try:
    # Assumes the script is in 'scripts/' directory, one level below project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Now try importing project-specific modules
    from projectdavid_common import UtilsInterface
    from projectdavid_common.utilities.logging_service import LoggingUtility

    from entities_api.models.models import ApiKey, User

except ImportError as e:
    print(f"Error: Could not import project modules: {e}")
    print("Please ensure:")
    print(f"  1. The script is run from the 'scripts' directory or the project root.")
    print(
        f"  2. The project root ('{project_root}') is correct and contains the necessary packages."
    )
    print(
        f"  3. Required packages ('projectdavid_common', 'entities_api') are installed."
    )
    sys.exit(1)
# --- End Path Adjustment & Imports ---


# --- Constants ---
DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_NAME = "Default Admin"
DEFAULT_ADMIN_KEY_NAME = "Admin Bootstrap Key"
DEFAULT_CREDENTIALS_FILENAME = "admin_credentials.txt"
DEFAULT_DOTENV_FILENAME = ".env"
ENV_VAR_API_KEY_ADMIN = "ADMIN_API_KEY"  # New primary key name for admin
ENV_VAR_API_KEY_ENTITIES = "ADMIN_API_KEY"  # Legacy/alternative key name
ENV_VAR_DB_URL = "SPECIAL_DB_URL"


# --- Setup ---
# Initialize utilities early, but handle potential errors if imports failed
try:
    logging_utility = LoggingUtility()
    identifier_service = UtilsInterface.IdentifierService()
except NameError:
    # Fallback if imports failed but we somehow continued
    print("Error: Failed to initialize utilities due to import errors.")
    sys.exit(1)


# --- Helper Functions ---


def setup_database(db_url: str) -> sessionmaker | None:
    """Connects to the database and returns a sessionmaker."""
    if not db_url:
        logging_utility.error(f"Database URL ({ENV_VAR_DB_URL}) is not configured.")
        print(
            f"Error: {ENV_VAR_DB_URL} environment variable not set or provided via --db-url."
        )
        return None
    try:
        engine = create_engine(db_url, echo=False, pool_pre_ping=True)  # Add pre-ping
        # Try connecting to catch immediate issues like wrong credentials/host
        with engine.connect() as connection:
            logging_utility.info(
                f"Successfully connected to database: {engine.url.database}"
            )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logging_utility.info("Database session factory configured.")
        return SessionLocal
    except sqlalchemy_exc.OperationalError as e:
        logging_utility.error(
            f"Failed to connect to database: {e}", exc_info=False
        )  # Less verbose log
        print(f"\nError: Could not connect to the database.")
        print(
            f"URL Used: {db_url[:15]}... (check full URL)"
        )  # Show partial URL for hint
        print(f"Details: {e}")
        print(f"Troubleshooting:")
        print(f"  - Is the database server running at the specified host/port?")
        print(f"  - Are the credentials (user/password) correct?")
        print(
            f"  - Is the database name ('{engine.url.database if 'engine' in locals() else 'N/A'}') correct?"
        )
        print(f"  - Is networking/firewall configured correctly between script and DB?")
        return None
    except Exception as e:
        logging_utility.error(
            f"Failed to initialize database engine: {e}", exc_info=True
        )
        print(f"\nError: An unexpected error occurred during database setup: {e}")
        return None


def find_or_create_admin_user(
    db: Session, admin_email: str, admin_name: str
) -> User | None:
    """Finds the admin user by email or creates a new one."""
    try:
        logging_utility.info(f"Checking for existing admin user: {admin_email}")
        admin_user = db.query(User).filter(User.email == admin_email).first()

        if admin_user:
            logging_utility.warning(
                f"Admin user '{admin_email}' already exists (ID: {admin_user.id})."
            )
            # Ensure the existing user has admin privileges if found by email
            if not admin_user.is_admin:
                logging_utility.warning(
                    f"Existing user {admin_email} found but IS NOT admin. Setting is_admin=True."
                )
                admin_user.is_admin = True
                admin_user.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(admin_user)
                logging_utility.info(f"User {admin_user.id} updated to be an admin.")
            return admin_user
        else:
            # --- Create New Admin User ---
            logging_utility.info(
                f"Creating new admin user: {admin_email}, Name: {admin_name}"
            )
            admin_user_id = identifier_service.generate_user_id()
            admin_user = User(
                id=admin_user_id,
                email=admin_email,
                full_name=admin_name,
                email_verified=True,  # Assume verified for bootstrap
                oauth_provider="local",  # Indicates created locally
                is_admin=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(admin_user)
            logging_utility.info(f"Admin user object created with ID: {admin_user.id}")
            db.commit()  # Commit user creation separately
            db.refresh(admin_user)
            logging_utility.info("Admin user committed to database.")
            return admin_user
    except Exception as e:
        logging_utility.error(
            f"Error finding or creating admin user '{admin_email}': {e}", exc_info=True
        )
        print(f"\nError: Failed during admin user lookup/creation: {e}")
        db.rollback()  # Rollback any partial changes
        return None


def generate_and_save_key(
    db: Session, admin_user: User, key_name: str
) -> tuple[str | None, str | None]:
    """Generates, hashes, and saves an API key for the admin user. Returns (plain_key, prefix) or (None, existing_prefix)."""
    plain_text_api_key = None
    key_prefix = None
    try:
        logging_utility.info(
            f"Checking for existing API key for admin user: {admin_user.id}"
        )
        existing_key = db.query(ApiKey).filter(ApiKey.user_id == admin_user.id).first()
        if existing_key:
            logging_utility.warning(
                f"Admin user {admin_user.id} already has an API key (Prefix: {existing_key.prefix}). Skipping key generation."
            )
            print(
                f"\nInfo: Admin user '{admin_user.email}' already has an API key. No new key generated."
            )
            # We don't have the plain text key here, so we can't save it again.
            # Return None to indicate no *new* key was generated.
            return None, existing_key.prefix  # Return None for key, but existing prefix

        logging_utility.info(
            f"Generating new API key '{key_name}' for admin user: {admin_user.id}"
        )

        # 1. Generate the plain text key (assuming 'ad_' prefix for admin)
        plain_text_api_key = ApiKey.generate_key(prefix="ad_")
        key_prefix = plain_text_api_key[:8]  # Standard prefix length

        # 2. Hash the key
        hashed_key = ApiKey.hash_key(plain_text_api_key)

        # 3. Create the ApiKey DB record
        api_key_record = ApiKey(
            user_id=admin_user.id,
            key_name=key_name,
            hashed_key=hashed_key,
            prefix=key_prefix,
            is_active=True,
            created_at=datetime.utcnow(),
            # expires_at=datetime.utcnow() + timedelta(days=365) # Optional expiration
        )
        db.add(api_key_record)
        logging_utility.info(f"API Key record created (Prefix: {key_prefix})")

        # 4. Commit the API Key
        db.commit()
        logging_utility.info("API Key record committed to database.")
        return plain_text_api_key, key_prefix

    except Exception as e:
        logging_utility.error(
            f"Error generating or saving API key for user {admin_user.id}: {e}",
            exc_info=True,
        )
        print(f"\nError: Failed during API key generation/saving: {e}")
        db.rollback()
        return None, None


def save_credentials(
    plain_text_key: str,
    key_prefix: str,
    admin_user: User,
    creds_file_path: str,
    dotenv_path: str,
):
    """Saves the generated credentials to the text file and .env file."""
    timestamp = datetime.utcnow().isoformat() + "Z"

    # --- Write details to text file ---
    logging_utility.info(f"Attempting to write credentials to: {creds_file_path}")
    try:
        os.makedirs(
            os.path.dirname(creds_file_path), exist_ok=True
        )  # Ensure directory exists
        # Prepare the content for the file
        file_content = (
            f"# Admin Credentials Generated: {timestamp}\n"
            f"# WARNING: Contains sensitive information. Secure this file and add to .gitignore.\n"
            f"ADMIN_USER_EMAIL={admin_user.email}\n"
            f"ADMIN_USER_ID={admin_user.id}\n"
            f"ADMIN_KEY_PREFIX={key_prefix}\n"
            f"{ENV_VAR_API_KEY_ADMIN}={plain_text_key}\n"  # Use constant
            f"{ENV_VAR_API_KEY_ENTITIES}={plain_text_key}\n"  # Also save legacy key
        )
        # Write/overwrite the file
        with open(creds_file_path, "w") as f:
            f.write(file_content)
        logging_utility.info(f"Successfully wrote credentials to: {creds_file_path}")
        print(f"\nInfo: Admin credentials written to: {creds_file_path}")
    except Exception as file_err:
        logging_utility.error(
            f"Failed to write credentials file '{creds_file_path}': {file_err}",
            exc_info=True,
        )
        print(
            f"\nWarning: Failed to write credentials file at {creds_file_path}: {file_err}"
        )
        # Continue to try writing to .env

    # --- Append/Update details in .env file ---
    logging_utility.info(f"Attempting to update .env file at: {dotenv_path}")
    try:
        os.makedirs(
            os.path.dirname(dotenv_path), exist_ok=True
        )  # Ensure directory exists
        # set_key creates the file if it doesn't exist.
        # Use quote_mode='always' for robustness
        set_key(dotenv_path, "ADMIN_USER_EMAIL", admin_user.email, quote_mode="always")
        set_key(
            dotenv_path, "ADMIN_USER_ID", str(admin_user.id), quote_mode="always"
        )  # Ensure ID is string
        set_key(dotenv_path, "ADMIN_KEY_PREFIX", key_prefix, quote_mode="always")
        # *** Write the key under BOTH names ***
        set_key(dotenv_path, ENV_VAR_API_KEY_ADMIN, plain_text_key, quote_mode="always")
        set_key(
            dotenv_path, ENV_VAR_API_KEY_ENTITIES, plain_text_key, quote_mode="always"
        )

        logging_utility.info(f"Successfully updated .env file: {dotenv_path}")
        print(f"Info: Admin credentials also updated in: {dotenv_path}")
        # Add a reminder about gitignore
        print(
            f"Info: Ensure '{os.path.basename(dotenv_path)}' and '{os.path.basename(creds_file_path)}' are in your .gitignore file!"
        )

    except Exception as dotenv_err:
        logging_utility.error(
            f"Failed to update .env file '{dotenv_path}': {dotenv_err}", exc_info=True
        )
        print(f"\nWarning: Failed to update .env file at {dotenv_path}: {dotenv_err}")


def print_key_to_console(
    user: User,
    key_prefix: str,
    plain_key: str,
    creds_filepath: str,
    dotenv_filepath: str,
):
    """Prints the generated key and confirmation details to the console."""
    print("\n" + "=" * 60)
    print("  IMPORTANT: Admin API Key Generated!")
    print(f"  User Email: {user.email}")
    print(f"  User ID:    {user.id}")
    print(f"  Key Prefix: {key_prefix}")
    print("-" * 60)
    print(f"  PLAIN TEXT API KEY: {plain_key}")
    print("-" * 60)
    print(f"  Store this key securely. Details also saved/updated in:")
    print(f"    1. Credentials File: {creds_filepath}")
    print(f"    2. DotEnv File:      {dotenv_filepath}")
    print(
        f"       (Key saved as both {ENV_VAR_API_KEY_ADMIN} and {ENV_VAR_API_KEY_ENTITIES})"
    )
    print("=" * 60 + "\n")


def parse_arguments():
    """Parses command-line arguments."""
    # Find .env before parsing args to potentially load default DB URL
    dotenv_path = find_dotenv(
        filename=DEFAULT_DOTENV_FILENAME, raise_error_if_not_found=False
    )
    load_dotenv(dotenv_path=dotenv_path)  # Load existing .env to get defaults

    parser = argparse.ArgumentParser(
        description="Bootstrap the initial admin user and API key for the Entities API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Get DB URL: Priority: CLI > Env > Error ---
    db_url_env = os.getenv(ENV_VAR_DB_URL)
    parser.add_argument(
        "--db-url",
        type=str,
        default=db_url_env,  # Use env var as default if set
        help=f"Database connection string (SQLAlchemy format). Overrides {ENV_VAR_DB_URL} env var.",
        required=db_url_env is None,  # Required only if env var is NOT set
    )

    parser.add_argument(
        "--email",
        type=str,
        default=os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL),
        help="Email address for the admin user. Overrides ADMIN_EMAIL env var.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=DEFAULT_ADMIN_NAME,
        help="Full name for the admin user.",
    )
    parser.add_argument(
        "--key-name",
        type=str,
        default=DEFAULT_ADMIN_KEY_NAME,
        help="Name for the initial admin API key.",
    )
    parser.add_argument(
        "--creds-file",
        type=str,
        # Default path relative to project root
        default=os.path.join(project_root, DEFAULT_CREDENTIALS_FILENAME),
        help="Full path to the output file for admin credentials (plain text).",
    )
    parser.add_argument(
        "--dotenv-path",
        type=str,
        # Use the found .env path as default, or construct one if not found
        default=dotenv_path or os.path.join(project_root, DEFAULT_DOTENV_FILENAME),
        help="Full path to the .env file to update.",
    )

    args = parser.parse_args()

    # Final check if DB URL is present after parsing
    if not args.db_url:
        parser.error(
            f"Database URL is required. Please set the {ENV_VAR_DB_URL} environment variable or use the --db-url argument."
        )

    return args


# --- Main Bootstrap Logic ---
def run_bootstrap(args):
    """Main function to coordinate the bootstrap process."""
    SessionLocal = setup_database(args.db_url)
    if not SessionLocal:
        sys.exit(1)  # Exit if DB setup failed

    db: Session | None = None  # Initialize db to None
    try:
        db = SessionLocal()
        # 1. Find or Create Admin User
        admin_user = find_or_create_admin_user(db, args.email, args.name)
        if not admin_user:
            raise Exception("Failed to find or create admin user.")  # Propagate error

        # 2. Generate and Save Key
        plain_text_key, key_prefix = generate_and_save_key(
            db, admin_user, args.key_name
        )

        # 3. Save Credentials and Print Output (only if a *new* key was generated)
        if plain_text_key and key_prefix:
            save_credentials(
                plain_text_key,
                key_prefix,
                admin_user,
                args.creds_file,
                args.dotenv_path,
            )
            print_key_to_console(
                admin_user,
                key_prefix,
                plain_text_key,
                args.creds_file,
                args.dotenv_path,
            )
        elif key_prefix:  # Existing key found, prefix was returned
            print(
                f"Admin user '{admin_user.email}' already exists with key prefix '{key_prefix}'."
            )
            print("No new credentials generated or saved.")
        else:
            # This case shouldn't happen if user exists but key gen failed, error handled in generate_and_save_key
            logging_utility.warning(
                "Key generation did not return a plain key or prefix."
            )

    except Exception as e:
        logging_utility.error(
            f"An critical error occurred during bootstrap: {e}", exc_info=True
        )
        print(f"\nCritical Error: Bootstrap process failed. Check logs. Error: {e}\n")
        # Rollback is handled within helper functions or commit only happens on success
        # db.rollback() might be redundant or cause issues if session already closed
    finally:
        if db and db.is_active:
            db.close()
            logging_utility.info("Database session closed.")


# --- Script Entry Point ---
if __name__ == "__main__":
    print("Starting admin user bootstrap process...")
    logging_utility.info("Admin bootstrap script started.")

    args = parse_arguments()
    logging_utility.info(
        f"Running with arguments: Email='{args.email}', DB URL='{args.db_url[:15]}...', Output Files='{args.creds_file}', '{args.dotenv_path}'"
    )

    # --- Pre-run Checks (Write Permissions) ---
    for path in [args.creds_file, args.dotenv_path]:
        target_dir = os.path.dirname(path)
        if not os.path.exists(target_dir):
            print(
                f"Info: Directory '{target_dir}' for output file '{os.path.basename(path)}' does not exist. Will attempt to create."
            )
            # Attempting creation is handled within save functions now
        elif not os.access(target_dir, os.W_OK):
            print(
                f"Warning: Write permission might be missing for directory: '{target_dir}'. Saving '{os.path.basename(path)}' might fail."
            )
            logging_utility.warning(
                f"Potential write permission issue for directory: '{target_dir}'"
            )

    # --- Execute Main Logic ---
    run_bootstrap(args)

    print("Bootstrap process finished.")
    logging_utility.info("Admin bootstrap script finished.")
