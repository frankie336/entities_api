
# Open Source Dev Environment Bootstrap Guide

A step-by-step guide to get your local development environment up and running.

---

## Prerequisites

- Python 3.10+  
- Docker & Docker Compose  
- A copy of the repository cloned locally  
- Your `.env` file in the project root (do **not** commit secrets)

---

## 1. Create Initial Admin User


1. **Build the initial containers**  
   ```bash
   python start.py
   ```

2**Run the bootstrap script**  
   ```bash
   python scripts/bootstrap_admin.py
   ```
3**Locate credentials**  
   - A file named `admin_credentials.txt` will be generated.  
   - **Do NOT** commit this file to Git.
4**Populate your `.env`**  
   Open `.env` and add:
   ```dotenv
   ADMIN_API_KEY=<value from admin_credentials.txt>
   ADMIN_USER_ID=<value from admin_credentials.txt>
   ```

---

## 2. Create Initial Normal User

1. **Run the user‐creation script**  
   ```bash
   python scripts/create_user.py
   ```
2. **Follow the interactive prompts**  
   - Copy the generated API key and user ID at the end.
3. **Update your `.env`**  
   ```dotenv
   ENTITIES_API_KEY=<value from prompt>
   ENTITIES_USER_ID=<value from prompt>
   ```

---

## 3. Rebuild & Restart the API Service

You must rebuild the API (and sandbox) service so that new environment variables are applied.

1. **Tear down any running containers**  
   ```bash
   python start.py --down
   ```
2. **Rebuild services**  
   - **Individually**:  
     ```bash
     python start.py --mode build --service api
     python start.py --mode build --service sandbox
     ```  
   - **Or both at once**:  
     ```bash
     python start.py --mode both
     ```

---

## 4. Configure Your Applications

Whether you’re working on the backend or frontend:

- Ensure your application’s environment (or settings) includes:
  ```dotenv
  ENTITIES_API_KEY=<from step 2>
  ENTITIES_USER_ID=<from step 2>
  ```

---

## 5. Verify

1. **Start the stack**  
   ```bash
   python start.py --mode up
   ```
2. **Log in as Admin**  
   - Use the credentials from `admin_credentials.txt`  
   - Confirm that you can create and view resources.
3. **Log in as Normal User**  
   - Use the credentials you saved from the create_user script  
   - Ensure permissions are applied correctly.

---

You’re now ready to develop against the open-source API stack! 🎉

1. **Use**  
   ```bash
   
   client = Entity(
    base_url=os.getenv("BASE_URL", "http://localhost:9000"),
    api_key=os.getenv("ENTITIES_API_KEY")
   )

   ```


