v
from urllib.parse import urlencode

import requests, json
# {
#  "plugin_id": "xxx",
#  "organization_id": "xxx",
#  "collection_name": "mycollection",
#  "bulk_write": false,
#  "object_id": "xxxx",
#  "filter": {},
#  "payload": {}
# }

PLUGIN_ID = "6135f65de2358b02686503a7"
ORG_ID = "6133c5a68006324323416896"

class DataStorage:
    def __init__(self, request=None):
        self.read_api = "https://api.zuri.chat/data/read/{pgn_id}/{collec_name}/{org_id}?{query}"
        self.write_api = "https://api.zuri.chat/data/write"
        if request is None:
            self.plugin_id = PLUGIN_ID
            self.organization_id = ORG_ID
        else:
            self.plugin_id = request.data.get("plugin_id")
            self.organization_id = request.data.get("org_id")
    
    def write(self, collection_name, data):
        body = dict(
            plugin_id=self.plugin_id,
            organization_id=self.organization_id,
            collection_name=collection_name,
            payload=data
        )
        try:
            response = requests.post(url=self.write_api, json=body)
        except requests.exceptions.RequestException as e:
            print(e)
            return None
        if response.status_code == 200:
            return response.json()
        else:
            return {
                "status_code": response.status_code,
                "message": response.reason
            }