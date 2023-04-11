import requests
from msal import ConfidentialClientApplication


class SharePointClient:
    def __init__(self, client_id, client_secret, tenant_id, site_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.authority = f'https://login.microsoftonline.com/{tenant_id}'
        self.scope = ['https://graph.microsoft.com/.default']
        self.site_url = site_url

        self.app = ConfidentialClientApplication(
            client_id=self.client_id, authority=self.authority,
            client_credential=self.client_secret
        )

    def acquire_token(self):
        result = self.app.acquire_token_silent(self.scope, account=None)

        if not result:
            result = self.app.acquire_token_for_client(scopes=self.scope)

        if "access_token" in result:
            return result['access_token']
        else:
            raise Exception("Error acquiring token: ", result.get("error"))

    def list_files(self, folder_server_relative_url):
        token = self.acquire_token()
        endpoint = f"{self.site_url}/_api/web/GetFolderByServerRelativeUrl('{folder_server_relative_url}')/Files"
        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json;odata=verbose'}
        response = requests.get(endpoint, headers=headers)

        if response.status_code == 200:
            files = response.json()['d']['results']
            return files
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

    def download_file(self, relative_path, local_path):
        token = self.acquire_token()
        download_url = f"{self.site_url}/_api/web/GetFileByServerRelativePath(decodedurl='{relative_path}')/$value"
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(download_url, headers=headers, stream=True)

        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"File downloaded to {local_path}")
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
