from pymongo import MongoClient
import os
from common import today

cluster=MongoClient(os.getenv("uri"))
db=cluster["yeon"]
collection = db["math"]
mongo_chats_collection = cluster["yeon"]["math"]

class MemoryManager:
    def save_chat(self, context):        
        messages = []
        for message in context:
            if message.get("saved", True): 
                continue
            messages.append({"date":today(), "role": message["role"], "content": message["content"]})
                        
        if len(messages) > 0:           
            mongo_chats_collection.insert_many(messages)

    def restore_chat(self, date=None):
        search_date = date if date is not None else today()        
        search_results = mongo_chats_collection.find({"date": search_date})
        restored_chat = [{"role": v['role'], "content": v['content'], "saved": True} for v in search_results]
        return restored_chat
    
    def save_message(self, role, content, user_id):  
        # Saving a single message, generalized for multiple uses.
        message = {"date": today(), "role": role, "content": content, "Userid": user_id}
        mongo_chats_collection.insert_one(message)