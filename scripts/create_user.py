# scripts/create_user.py
import argparse
import os
import sys
import time

from dotenv import load_dotenv

try:
    from projectdavid import Entity
except ImportError:
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
DEFAULT_VECTOR_STORE_NAME = "file_search"


# --- Helper Functions ---
def load_admin_key(env_var="ADMIN_API_KEY", creds_file=DEFAULT_CREDS_FILE):
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
                admin_api_key = None

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
    try:
        client = Entity(base_url=base_url, api_key=api_key)
        if not hasattr(client, "users") or not hasattr(client, "keys"):
            print(
                "Warning: API client might not be fully initialized. Missing 'users' or 'keys' attribute."
            )
        return client
    except Exception as e:
        print(f"Error initializing API client for base_workers URL {base_url}: {e}")
        sys.exit(1)


def create_user(client, full_name, email):
    print(f"\nAttempting to create user '{full_name}' ({email})...")
    try:
        new_user = client.users.create_user(
            full_name=full_name,
            email=email,
            is_admin=False,
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
        return None


def create_user_vector_store(client, user, store_name=DEFAULT_VECTOR_STORE_NAME):
    if not user or not getattr(user, "id", None):
        print("\n[vector-store] skipped – user instance missing or invalid.")
        return None

    try:
        print(f"\nCreating vector-store '{store_name}' for user {user.id} …")
        vs = client.vectors.create_vector_store_for_user(
            owner_id=user.id,
            name=store_name,
        )
        vs_id = getattr(vs, "id", "N/A")
        print("✅  Vector-store created.")
        print(f"   Vector-store ID: {vs_id}")
        print(f"   Name:           {getattr(vs, 'name', store_name)}")
        return vs
    except Exception as e:
        print(f"❌  Failed to create vector-store: {e}")
        eresp = getattr(e, "response", None)
        if eresp is not None:
            print(f"Status Code: {eresp.status_code}")
            try:
                print(f"Body: {eresp.json()}")
            except Exception:
                print(f"Body: {eresp.text}")
        return None


def generate_user_key(admin_client, user, key_name=DEFAULT_KEY_NAME):
    if not user or not hasattr(user, "id"):
        print(
            "\nSkipped API key generation because user object is invalid or missing ID."
        )
        return None

    target_user_id = user.id
    user_email = getattr(user, "email", "N/A")

    print(
        f"\nAttempting to generate initial API key for user {target_user_id} ({user_email})..."
    )

    try:
        key_payload = {"key_name": key_name}

        print(
            f"Calling SDK method 'create_key_for_user' on admin client for user ID {target_user_id}"
        )
        key_creation_response = admin_client.keys.create_key_for_user(
            target_user_id=target_user_id,
            **key_payload,
        )

        plain_text_key = getattr(key_creation_response, "plain_key", None)
        if plain_text_key:
            print("\n" + "=" * 50)
            print("  Initial API Key Generated for Regular User (by Admin)!")
            print(f"  User ID:    {target_user_id}")
            print(f"  User Email: {user_email}")
            key_details = getattr(key_creation_response, "details", None)
            if key_details and hasattr(key_details, "prefix"):
                print(f"  Key Prefix: {key_details.prefix}")
                print(f"  Key Name:   {getattr(key_details, 'name', 'N/A')}")
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
        "--base_workers-url",
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

    load_dotenv()

    try:
        admin_api_key = load_admin_key(creds_file=args.creds_file)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    admin_client = create_api_client(args.base_url, admin_api_key)

    user_email = args.email or f"test_regular_user_{int(time.time())}@example.com"
    user_full_name = args.name or "Regular User Test"

    new_user = create_user(admin_client, user_full_name, user_email)

    if new_user:
        vector_store = create_user_vector_store(admin_client, new_user)
        generated_key = generate_user_key(
            admin_client, new_user, key_name=args.key_name
        )

        # ✨ Append vector-store summary at bottom
        if vector_store:
            print("\n" + "=" * 50)
            print("  Vector Store Details (created for new user):")
            print(f"  Store ID:   {getattr(vector_store, 'id', 'N/A')}")
            print(f"  Store Name: {getattr(vector_store, 'name', 'N/A')}")
            print("=" * 50 + "\n")
    else:
        print("\nSkipping key / vector-store creation because user-creation failed.")

    print("Script finished.")


if __name__ == "__main__":
    main()
