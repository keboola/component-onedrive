import requests
import logging
import os
from msal import ConfidentialClientApplication
import fnmatch


class OneDriveBusinessClientException(Exception):
    pass


class OneDriveBusinessClient:
    def __init__(self, refresh_token, files_out_folder, client_id, client_secret, tenant_id, site_name):
        self.files_out_folder = files_out_folder
        self.refresh_token = refresh_token
        self.access_token = None
        self.tenant_id = tenant_id
        self.authority = f'https://login.microsoftonline.com/{tenant_id}'
        self.scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        self.client_id = client_id
        self.client_secret = client_secret

        self.app = ConfidentialClientApplication(
            client_id=client_id, authority=self.authority,
            client_credential=client_secret
        )

        self.get_access_token(refresh_token=refresh_token)
        self.site_id, self.site_url = self.get_site_id_and_url(site_name)
        self.endpoint = f'https://graph.microsoft.com/v1.0/sites/{self.site_id}'

    def get_access_token(self, refresh_token: str):
        if self.access_token:
            # check if access token is present and valid
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
            raise OneDriveBusinessClientException("Cannot fetch Access token")
        logging.info("Access token fetched")
        self.access_token = response.json()["access_token"]

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
            raise OneDriveBusinessClientException(f"Error occurred when getting folder content:"
                                                  f" {response.status_code}, {response.text}")

    def download_file_from_onedrive_url(self, url, output_path):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers, stream=True)

        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logging.info(f"File downloaded to {output_path}")
        else:
            raise Exception(f"Error downloading file: {response.status_code}, {response.text}")

    def download_files(self, folder_path, file_mask, output_dir):
        items = self.list_folder_contents(folder_path)

        for item in items:
            if item.get('file') is not None:
                if fnmatch.fnmatch(item['name'], file_mask):
                    logging.info(f"Downloading file {item['name']} ...")
                    file_url = item['@microsoft.graph.downloadUrl']
                    output_path = os.path.join(output_dir, item['name'])
                    self.download_file_from_onedrive_url(file_url, output_path)

            elif item.get('folder') is not None:
                if folder_path == "/":
                    subfolder_path = f"{folder_path}{item['name']}"
                else:
                    subfolder_path = f"{folder_path}/{item['name']}"
                self.download_files(subfolder_path, file_mask, output_dir)

    def get_site_id_and_url(self, site_name):
        search_url = f"https://graph.microsoft.com/v1.0/sites?search={site_name}"
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(search_url, headers=headers)
        if response.status_code == 200:
            sites = response.json()['value']
            if len(sites) > 0:
                site = sites[0]  # Assuming the first result is the desired site
                site_id = site['id']
                site_url = site['webUrl']
                return site_id, site_url
            else:
                raise OneDriveBusinessClientException("No site found with the given name")
        else:
            raise OneDriveBusinessClientException(f"Error occurred when searching for the site:"
                                                  f" {response.status_code}, {response.text}")
