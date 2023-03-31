import requests
from msal import ConfidentialClientApplication
import logging
import json


class OneDriveClient:
    def __init__(self, client_id, client_secret, tenant_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.authority = f'https://login.microsoftonline.com/{tenant_id}'
        self.scope = ['https://graph.microsoft.com/.default']
        self.endpoint = 'https://graph.microsoft.com/v1.0/users'

        self.app = ConfidentialClientApplication(
            client_id=self.client_id, authority=self.authority,
            client_credential=self.client_secret
        )

    def acquire_token(self):
        result = self.app.acquire_token_silent(self.scope, account=None)

        if not result:
            logging.info("No suitable token exists in cache. Let's get a new one from AAD.")
            result = self.app.acquire_token_for_client(scopes=self.scope)

        if "access_token" in result:
            # Calling graph using the access token
            graph_data = requests.get(  # Use token to call downstream service
                self.endpoint,
                headers={'Authorization': 'Bearer ' + result['access_token']}, ).json()
            print("Graph API call result: %s" % json.dumps(graph_data, indent=2))

    def list_folder_contents(self, folder_id=None):
        token = self.acquire_token()
        folder_path = f"{self.endpoint}/root/children" if folder_id is None else \
            f"{self.endpoint}/items/{folder_id}/children"

        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(folder_path, headers=headers)

        if response.status_code == 200:
            items = response.json()['value']
            return items
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

    def download_file(self, item_id, local_path):
        token = self.acquire_token()
        download_url = f"{self.endpoint}/items/{item_id}/content"
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(download_url, headers=headers, stream=True)

        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"File downloaded to {local_path}")
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

