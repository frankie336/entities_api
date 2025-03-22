from fastapi import  WebSocket



# Dictionary to manage connections by room/user_id
rooms = {}

# Utility function to add/remove clients to/from rooms
def add_to_room(room_name: str, websocket: WebSocket):
    if room_name not in rooms:
        rooms[room_name] = []
    rooms[room_name].append(websocket)

def remove_from_room(room_name: str, websocket: WebSocket):
    if room_name in rooms and websocket in rooms[room_name]:
        rooms[room_name].remove(websocket)

async def broadcast_to_room(room_name: str, message: str, sender: WebSocket):
    """Broadcast message to all clients in the specified room."""
    if room_name in rooms:
        for connection in rooms[room_name]:
            if connection != sender:
                await connection.send_text(message)
