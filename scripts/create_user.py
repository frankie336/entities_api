# scripts/create_user.py
import os
import sys
import time  # Import time for potential delays/debugging

from dotenv import load_dotenv
# Assuming projectdavid.Entity correctly initializes ApiKeysClient under .keys
from projectdavid import Entity

# Add project root to path to find projectdavid module if needed
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# sys.path.insert(0, project_root)


# --- Load Environment Variables ---
load_dotenv()

# --- Get Admin API Key ---
admin_api_key = os.getenv("ADMIN_API_KEY")
if not admin_api_key:
    creds_file = "admin_credentials.txt"
    if os.path.exists(creds_file):
        print(f"ADMIN_API_KEY not found in env, attempting to read from {creds_file}")
        with open(creds_file, "r") as f:
            for line in f:
                if line.startswith("ADMIN_API_KEY="):
                    admin_api_key = line.strip().split("=", 1)[1]
                    break
    if not admin_api_key:
        raise ValueError(
            "ADMIN_API_KEY not found. "
            "Please run 'scripts/bootstrap_admin.py' and ensure the key is available "
            "either in your environment variables or in admin_credentials.txt."
        )

print(f"Using Admin API Key starting with: {admin_api_key[:4]}...{admin_api_key[-4:]}")

# --- Initialize Client WITH Admin Key ---
# This client instance is authenticated as the Admin
admin_client = Entity(base_url="http://localhost:9000", api_key=admin_api_key)

# --- Variables ---
new_regular_user = None  # Initialize variable to hold the user object

# --- Create a NEW REGULAR User using the Admin Client ---
print("\nAttempting to create a NEW REGULAR user using the Admin API Key...")

try:
    # Generate a unique email using timestamp to avoid conflicts on reruns
    regular_user_email = f"test_regular_user_{int(time.time())}@example.com"
    regular_user_full_name = "Regular User Test"

    # Call the create_user method via the admin-authenticated client
    # Assumes this uses POST /v1/admin/users or similar admin-privileged route
    new_regular_user = admin_client.users.create_user(
        full_name=regular_user_full_name,
        email=regular_user_email,
        is_admin=False,  # Explicitly set to False
    )

    print("\nNew REGULAR user created successfully by admin:")
    print(f"  User ID:    {getattr(new_regular_user, 'id', 'N/A')}")
    print(f"  User Email: {getattr(new_regular_user, 'email', 'N/A')}")
    # Ensure your user creation endpoint/SDK actually returns is_admin
    print(f"  Is Admin:   {getattr(new_regular_user, 'is_admin', 'N/A')}")


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
    print("\nSkipping API key generation due to user creation failure.")
    new_regular_user = None

# --- Generate Initial Key for the NEW Regular User (If User Creation Succeeded) ---
if new_regular_user and hasattr(new_regular_user, "id"):
    target_user_id = new_regular_user.id
    print(
        f"\nAttempting to generate initial API key for user {target_user_id} using admin credentials..."
    )
    try:
        # Define optional payload for the key creation
        key_payload = {
            "key_name": "Default Initial Key"
            # "expires_in_days": 365 # Optional: Example
        }

        # *** CORRECTED METHOD CALL: Use the actual method name from the SDK ***
        # Calls the `create_key_for_user` method in ApiKeysClient, which targets
        # the ADMIN endpoint POST /v1/admin/users/{target_user_id}/keys
        print(
            f"Calling SDK method 'create_key_for_user' targeting ADMIN endpoint: POST /v1/admin/users/{target_user_id}/keys"
        )
        key_creation_response = admin_client.keys.create_key_for_user(  # <--- FIXED METHOD NAME
            target_user_id=target_user_id,  # Pass the ID of the user to create the key for
            **key_payload,  # Pass optional name/expiration
        )
        # *** END CORRECTION ***

        # Process the response (assuming it follows ApiKeyCreateResponse schema)
        if (
            hasattr(key_creation_response, "plain_key")
            and key_creation_response.plain_key
        ):
            plain_text_key_for_regular_user = key_creation_response.plain_key

            print("\n" + "=" * 50)
            print("  Initial API Key Generated for Regular User (by Admin)!")
            print(f"  User ID:    {target_user_id}")
            print(
                f"  User Email: {getattr(new_regular_user, 'email', 'N/A')}"
            )  # Get email again for clarity
            key_details = getattr(key_creation_response, "details", None)
            if key_details and hasattr(key_details, "prefix"):
                print(f"  Key Prefix: {key_details.prefix}")
            print("-" * 50)
            print(f"  PLAIN TEXT API KEY: {plain_text_key_for_regular_user}")
            print("-" * 50)
            print("  Provide this key to the regular user. They can use it")
            print("  to authenticate and manage their own keys via the API")
            print(
                f"  (e.g., using their key with POST /v1/users/{target_user_id}/apikeys)."
            )  # User self-service endpoint
            print("=" * 50 + "\n")
        else:
            print(
                "\nAdmin key generation API call successful, but plain text key not found in the response."
            )
            print(
                f"Check the API endpoint (POST /v1/admin/users/{target_user_id}/keys) response structure."
            )
            print(f"Response details received: {key_creation_response}")

    except AttributeError as ae:
        # This error should now be resolved if the SDK client is correctly imported/attached
        print("\n--- SDK ERROR ---")
        print(f"AttributeError: {ae}")
        print("Could not find the required method on the SDK client.")
        print(
            "Verify the SDK structure is correctly initialized (e.g., `admin_client.keys` exists)"
        )
        print("and the method `create_key_for_user` exists in the `ApiKeysClient`.")
        print(
            "Ensure your `projectdavid.Entity` properly attaches the `ApiKeysClient` as `.keys`."
        )
        print("--- END SDK ERROR ---")
    except Exception as key_gen_e:
        # Handle other errors (e.g., HTTP errors from API like 403 Forbidden if admin key lacks permission, 404 if endpoint wrong)
        print(
            f"\nError generating key for user {target_user_id} via admin endpoint: {key_gen_e}"
        )
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
                    f"Hint: Ensure the admin endpoint (POST /v1/admin/users/{target_user_id}/keys) exists in your API and is correctly mapped."
                )
            elif error_response.status_code == 403:
                print(
                    "Hint: Ensure the ADMIN_API_KEY used has the necessary admin permissions configured in the API backend."
                )
            elif error_response.status_code == 422:
                print(
                    "Hint: Check the payload being sent (key_name, expires_in_days) against the API's expectations."
                )
        else:
            # Print general exception if it's not an httpx error with a response
            print(f"An unexpected error occurred: {key_gen_e}")

else:
    if not new_regular_user:
        print("\nSkipped API key generation because user creation failed.")
    elif not hasattr(new_regular_user, "id"):
        print(
            "\nSkipped API key generation because the created user object is missing an 'id' attribute."
        )


print("\nScript finished.")
