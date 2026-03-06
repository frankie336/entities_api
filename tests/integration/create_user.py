import os

from dotenv import load_dotenv

load_dotenv()
from projectdavid import Entity

client = Entity(api_key=os.getenv("ADMIN_API_KEY"))


create_api_key = client.keys.create_key_for_user(
    target_user_id="user_h5YYXC9b200Xv3QYT0Bv12", key_name="The Grid"
)

print(create_api_key.plain_key)
