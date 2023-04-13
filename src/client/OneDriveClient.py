import requests
import logging
from msal import ConfidentialClientApplication
import fnmatch
import os


class OneDriveClientException(Exception):
    pass


class OneDriveClient:
    def __init__(self, refresh_token, files_out_folder, client_id, client_secret):
        self.files_out_folder = files_out_folder
        self.refresh_token = refresh_token
        self.access_token = None
        self.endpoint = 'https://graph.microsoft.com/v1.0/me'
        self.authority = 'https://login.microsoftonline.com/common'
        self.scope = ['https://graph.microsoft.com/User.Read', 'https://graph.microsoft.com/Files.Read.All']
        self.client_id = client_id
        self.client_secret = client_secret

        self.app = ConfidentialClientApplication(
            client_id=client_id, authority=self.authority,
            client_credential=client_secret
        )

        self.get_access_token(refresh_token=refresh_token)
        self.downloaded_files = []

    def get_access_token(self, refresh_token: str):
        if self.access_token:
            headers = {'Authorization': f'Bearer {self.access_token}'}
            response = requests.get(self.endpoint, headers=headers)
            if response.status_code == 200:
                logging.info("Access token is valid")
                return

        request_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        response = requests.post(url=request_url, headers=headers, data=payload)
        token = response.json().get("access_token", None)
        if not token:
            logging.error(response.json())
            raise OneDriveClientException("Cannot fetch Access token")
        logging.info("Access token fetched")
        self.access_token = response.json()["access_token"]

    def list_users(self):
        endpoint = 'https://graph.microsoft.com/v1.0/users'
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(endpoint, headers=headers)
        if response.status_code == 200:
            users = response.json()['value']
            return users
        else:
            raise Exception(f"Error occured when listing users: {response.status_code}, {response.text}")

    def list_folder_contents(self, folder_path=None):
        if folder_path is None or folder_path == '/':
            folder_id = 'root'
        else:
            # Resolve the path to a folder id
            drive_root = f"{self.endpoint}/drive/root"
            headers = {'Authorization': f'Bearer {self.access_token}'}
            response = requests.get(f"{drive_root}:/{'/'.join(folder_path.split('/')[1:])}:/", headers=headers)
            if response.status_code == 200:
                folder_id = response.json()['id']
            else:
                raise Exception(f"Error resolving folder path '{folder_path}': {response.status_code}, {response.text}")

        folder_path = f"{self.endpoint}/drive/root/children" if folder_id == 'root' else \
            f"{self.endpoint}/drive/items/{folder_id}/children"

        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(folder_path, headers=headers)

        if response.status_code == 200:
            items = response.json()['value']
            return items
        else:
            raise OneDriveClientException(f"Error occurred when getting folder content:"
                                          f" {response.status_code}, {response.text}")

    def download_file_from_onedrive_url(self, url, output_path, filename):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers, stream=True)

        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=32768):
                    f.write(chunk)
            logging.info(f"File downloaded to {output_path}")
        else:
            raise Exception(f"Error downloading file: {response.status_code}, {response.text}")

        if filename in self.downloaded_files:
            logging.warning(f"File {filename} has the same as an already downloaded file. It will be overwritten.")
        self.downloaded_files.append(filename)

    def download_files(self, folder_path, output_dir, file_mask="*"):
        items = self.list_folder_contents(folder_path)
        for item in items:
            # logging.info(item["name"])
            if item.get('file') is not None:
                if fnmatch.fnmatch(item['name'], file_mask):
                    logging.info(f"Downloading file {item['name']} ...")
                    file_url = item['@microsoft.graph.downloadUrl']
                    output_path = os.path.join(output_dir, item['name'])
                    self.download_file_from_onedrive_url(file_url, output_path, filename=item["name"])

            elif item.get('folder') is not None:
                if folder_path == "/":
                    subfolder_path = f"{folder_path}{item['name']}"
                else:
                    subfolder_path = f"{folder_path}/{item['name']}"
                self.download_files(subfolder_path, output_dir, file_mask)
