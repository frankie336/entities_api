# scripts/create_user.py
import argparse
import os
import sys
import time

from dotenv import load_dotenv

# Assuming projectdavid.Entity correctly initializes ApiKeysClient under .keys
# Make sure this import works based on your project structure.
# If running from the 'scripts' directory, you might need to adjust sys.path
try:
    from projectdavid import Entity
except ImportError:
    # Add project root to path if 'projectdavid' is not found directly
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        from projectdavid import Entity
    except ImportError:
        print(
            "Error: Could not import 'projectdavid'. "
            "Make sure the package is installed or the project root is in PYTHONPATH."
        )
        sys.exit(1)


# --- Constants ---
DEFAULT_BASE_URL = "http://localhost:9000"
DEFAULT_CREDS_FILE = "admin_credentials.txt"
DEFAULT_KEY_NAME = "Default Initial Key"


# --- Helper Functions ---
def load_admin_key(env_var="ADMIN_API_KEY", creds_file=DEFAULT_CREDS_FILE):
    """Loads the Admin API key from environment or a credentials file."""
    admin_api_key = os.getenv(env_var)
    if not admin_api_key:
        if os.path.exists(creds_file):
            print(f"{env_var} not found in env, attempting to read from {creds_file}")
            try:
                with open(creds_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith(f"{env_var}="):
                            admin_api_key = line.split("=", 1)[1]
                            break
            except Exception as e:
                print(f"Error reading {creds_file}: {e}")
                admin_api_key = None  # Ensure it's None if reading fails

        if not admin_api_key:
            raise ValueError(
                f"{env_var} not found. "
                f"Please set it as an environment variable or ensure it's in {creds_file}. "
                "You might need to run 'scripts/bootstrap_admin.py' first."
            )
    print(
        f"Using Admin API Key starting with: {admin_api_key[:4]}...{admin_api_key[-4:]}"
    )
    return admin_api_key


def create_api_client(base_url, api_key):
    """Initializes the API client."""
    try:
        client = Entity(base_url=base_url, api_key=api_key)
        # Simple check if client has expected attributes (optional but good practice)
        if not hasattr(client, "users") or not hasattr(client, "keys"):
            print(
                "Warning: API client might not be fully initialized. Missing 'users' or 'keys' attribute."
            )
        return client
    except Exception as e:
        print(f"Error initializing API client for base URL {base_url}: {e}")
        sys.exit(1)


def create_user(client, full_name, email):
    """Creates a new regular user using the admin client."""
    print(f"\nAttempting to create user '{full_name}' ({email})...")
    try:
        # Assumes admin_client.users.create_user handles the API call
        new_user = client.users.create_user(
            full_name=full_name,
            email=email,
            is_admin=False,  # Explicitly creating a regular user
        )
        print("\nNew REGULAR user created successfully:")
        print(f"  User ID:    {getattr(new_user, 'id', 'N/A')}")
        print(f"  User Email: {getattr(new_user, 'email', 'N/A')}")
        print(f"  Is Admin:   {getattr(new_user, 'is_admin', 'N/A')}")
        return new_user
    except Exception as e:
        print(f"\nError creating regular user: {e}")
        error_response = getattr(e, "response", None)
        if error_response is not None:
            print(f"Status Code: {error_response.status_code}")
            try:
                error_detail = error_response.json()
            except Exception:
                error_detail = error_response.text
            print(f"Response Body: {error_detail}")
        return None  # Indicate failure


def generate_user_key(admin_client, user, key_name=DEFAULT_KEY_NAME):
    """Generates an initial API key for the specified user using admin credentials."""
    if not user or not hasattr(user, "id"):
        print(
            "\nSkipped API key generation because user object is invalid or missing ID."
        )
        return None

    target_user_id = user.id
    user_email = getattr(user, "email", "N/A")  # For logging

    print(
        f"\nAttempting to generate initial API key for user {target_user_id} ({user_email})..."
    )

    try:
        # Define optional payload for the key creation
        key_payload = {
            "key_name": key_name
            # "expires_in_days": 365 # Optional: Example
        }

        # Use the create_key_for_user method via the admin client's keys interface
        print(
            f"Calling SDK method 'create_key_for_user' on admin client for user ID {target_user_id}"
        )
        key_creation_response = admin_client.keys.create_key_for_user(
            target_user_id=target_user_id,
            **key_payload,
        )

        # Process the response
        plain_text_key = getattr(key_creation_response, "plain_key", None)
        if plain_text_key:
            print("\n" + "=" * 50)
            print("  Initial API Key Generated for Regular User (by Admin)!")
            print(f"  User ID:    {target_user_id}")
            print(f"  User Email: {user_email}")
            key_details = getattr(key_creation_response, "details", None)
            if key_details and hasattr(key_details, "prefix"):
                print(f"  Key Prefix: {key_details.prefix}")
                print(
                    f"  Key Name:   {getattr(key_details, 'name', 'N/A')}"
                )  # Assuming name is in details
            print("-" * 50)
            print(f"  PLAIN TEXT API KEY: {plain_text_key}")
            print("-" * 50)
            print("  Provide this key to the regular user for API access.")
            print("=" * 50 + "\n")
            return plain_text_key
        else:
            print(
                "\nAPI call successful, but plain text key not found in the response."
            )
            print(f"Response details received: {key_creation_response}")
            return None

    except AttributeError as ae:
        print("\n--- SDK ERROR ---")
        print(f"AttributeError: {ae}")
        print(
            "Could not find the required method (e.g., `create_key_for_user`) on the SDK client."
        )
        print(
            "Verify that `projectdavid.Entity` correctly initializes and attaches the `ApiKeysClient` as `.keys`."
        )
        print("--- END SDK ERROR ---")
        return None
    except Exception as key_gen_e:
        print(f"\nError generating key for user {target_user_id}: {key_gen_e}")
        error_response = getattr(key_gen_e, "response", None)
        if error_response is not None:
            print(f"Status Code: {error_response.status_code}")
            try:
                error_detail = error_response.json()
            except Exception:
                error_detail = error_response.text
            print(f"Response Body: {error_detail}")
            # Add hints based on status code
            if error_response.status_code == 404:
                print(
                    f"Hint: Check API endpoint POST /v1/admin/users/{target_user_id}/keys"
                )
            elif error_response.status_code == 403:
                print("Hint: Ensure the ADMIN_API_KEY has permission.")
            elif error_response.status_code == 422:
                print("Hint: Check the key_payload against API expectations.")
        else:
            print(f"An unexpected error occurred: {key_gen_e}")
        return None


def main():
    """Main script execution function."""
    parser = argparse.ArgumentParser(
        description="Create a new regular user and generate an initial API key using admin credentials."
    )
    parser.add_argument(
        "-e",
        "--email",
        type=str,
        help="Email address for the new user. If omitted, a unique default is generated.",
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        help="Full name for the new user. If omitted, a default name is used.",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help=f"Base URL for the API. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--creds-file",
        type=str,
        default=DEFAULT_CREDS_FILE,
        help=f"Path to the admin credentials file. Default: {DEFAULT_CREDS_FILE}",
    )
    parser.add_argument(
        "--key-name",
        type=str,
        default=DEFAULT_KEY_NAME,
        help=f"Name for the initial API key generated for the user. Default: '{DEFAULT_KEY_NAME}'",
    )

    args = parser.parse_args()

    # --- Load Environment Variables ---
    load_dotenv()

    # --- Get Admin API Key ---
    try:
        admin_api_key = load_admin_key(creds_file=args.creds_file)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # --- Initialize Admin Client ---
    admin_client = create_api_client(args.base_url, admin_api_key)

    # --- Determine User Details ---
    user_email = args.email or f"test_regular_user_{int(time.time())}@example.com"
    user_full_name = args.name or "Regular User Test"

    # --- Create User ---
    new_user = create_user(admin_client, user_full_name, user_email)

    # --- Generate Key (if user created) ---
    if new_user:
        generate_user_key(admin_client, new_user, key_name=args.key_name)
    else:
        print("\nSkipping API key generation due to user creation failure.")

    print("\nScript finished.")


if __name__ == "__main__":
    main()
