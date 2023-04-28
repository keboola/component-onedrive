import requests
import logging
import fnmatch
import os
from datetime import datetime
import backoff
from client import exceptions


class OneDriveClientException(Exception):
    pass


class OneDriveClient:
    def __init__(self, refresh_token, files_out_folder, client_id, client_secret, tenant_id=None, site_name=None):
        self.files_out_folder = files_out_folder
        self.refresh_token = refresh_token
        self.access_token = None
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.site_name = site_name
        self.client_type, self.authority, self.endpoint, self.scope = self.configure_client()
        if not self.access_token:
            self.get_access_token(refresh_token=refresh_token)
        self.downloaded_files = []
        self.freshest_file_timestamp = None

    def configure_client(self):
        if not self.tenant_id and not self.site_name:
            return self.configure_onedrive_client()
        elif self.tenant_id and self.site_name:
            return self.configure_sharepoint_client()
        elif self.tenant_id and not self.site_name:
            return self.configure_onedrive_for_business_client()
        else:
            raise OneDriveClientException(f"Unsupported settings: {self.tenant_id}, {self.site_name}")

    @staticmethod
    def configure_onedrive_client():
        logging.info("Initializing OneDrive client")
        client_type = "OneDrive"
        authority = 'https://login.microsoftonline.com/common'
        endpoint = 'https://graph.microsoft.com/v1.0/me'
        scope = ['https://graph.microsoft.com/User.Read', 'https://graph.microsoft.com/Files.Read.All']
        return client_type, authority, endpoint, scope

    def configure_sharepoint_client(self):
        logging.info("Initializing Sharepoint client")
        client_type = "Sharepoint"
        authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.scope = scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        # We need access token to get site id and url
        self.get_access_token(refresh_token=self.refresh_token)
        site_id, site_url = self.get_site_id_and_url(self.site_name)
        endpoint = f'https://graph.microsoft.com/v1.0/sites/{site_id}'
        return client_type, authority, endpoint, scope

    def configure_onedrive_for_business_client(self):
        logging.info("Initializing OneDriveForBusiness client")
        client_type = "OneDriveForBusiness"
        authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        endpoint = 'https://graph.microsoft.com/v1.0/me/drive'
        scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        return client_type, authority, endpoint, scope

    def get_access_token(self, refresh_token: str) -> None:
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

    def list_folder_contents(self, folder_path=None):
        if folder_path is None or folder_path == '/':
            folder_id = 'root'
        else:
            # Resolve the path to a folder id
            drive_root = f"{self.endpoint}/drive/root"
            headers = {'Authorization': f'Bearer {self.access_token}'}
            url = f"{drive_root}:/{folder_path.lstrip('/')}:/"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                folder_id = response.json()['id']
            else:
                raise OneDriveClientException(f"Error resolving folder path '{folder_path}': "
                                              f"{response.status_code}, {response.text}")

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

    def list_folder_contents_ofb(self, folder_path=None):
        if folder_path is None or folder_path == '/':
            folder_id = 'root'
        else:
            # Resolve the path to a folder id
            drive_root = f"{self.endpoint}/root"
            headers = {'Authorization': f'Bearer {self.access_token}'}
            url = f"{drive_root}:/{folder_path.strip('/')}:/"
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                folder_id = response.json()['id']
            else:
                raise Exception(f"Error resolving folder path '{folder_path}': {response.status_code}, {response.text}")

        folder_path = f"{self.endpoint}/root/children" if folder_id == 'root' else \
            f"{self.endpoint}/items/{folder_id}/children"

        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(folder_path, headers=headers)

        if response.status_code == 200:
            items = response.json()['value']
            return items
        else:
            raise OneDriveClientException(f"Error occurred when getting folder content:"
                                          f" {response.status_code}, {response.text}")

    def list_folder_contents_sharepoint(self, folder_path=None):
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
                raise OneDriveClientException(f"Error resolving folder path '{folder_path}': "
                                              f"{response.status_code}, {response.text}")

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

    def get_site_id_and_url(self, site_name):
        """Returns site_id and url for Sharepoint site_name"""
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
                raise OneDriveClientException("No site found with the given name")
        else:
            raise OneDriveClientException(f"Error occurred when searching for the site:"
                                          f" {response.status_code}, {response.text}")

    @backoff.on_exception(backoff.expo, Exception, max_tries=6)
    def download_file_from_onedrive_url(self, url, output_path, filename):
        """
        Downloads a file from OneDrive using the provided download URL and saves it to the specified output path.

        Args:
            url (str): The download URL for the file on OneDrive.
            output_path (str): The path where the downloaded file will be saved.
            filename (str): The name of the file being downloaded.

        Raises:
            Exception: If an error occurs while downloading the file or if the response status code is not 200.

        Retry behavior:
            The method will retry up to 6 times with an exponential backoff strategy in the following cases:
                - Any exception is raised during the download process.
                - An error occurs while downloading the file and the response status code is not 200.
            If the maximum number of retries is reached and the error persists, the method will raise an exception
            and the download will be considered as failed.

        Note:
            This method does not retry in cases where the error is not recoverable, such as when the provided
            download URL is invalid or the local file system runs out of space.
        """

        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers, stream=True)

        try:
            parsed_response = self._parse_response(response, url)
            if parsed_response is not None:
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=32768):
                        f.write(chunk)
                logging.info(f"File {filename} downloaded.")
            else:
                logging.warning(f"No content in the response for file {filename}.")
        except exceptions.OneDriveClientException as e:
            raise e

        if filename in self.downloaded_files:
            logging.warning(f"File {filename} has the same as an already downloaded file. It will be overwritten.")
        self.downloaded_files.append(filename)

    def download_files(self, file_path, output_dir, last_modified_at=None):
        """
        Downloads files from a OneDrive folder to a local directory.

        Args:
            file_path (str): The path of the file to download files from. Use '/' to specify the root folder.
            output_dir (str): The path of the local directory to save the downloaded files to.
            sequence of characters, or '?' to match any single character.
            last_modified_at (datetime.datetime, optional): A datetime object representing the minimum last modified
            date and time of files to download. If provided, only files that were last modified on or after this date
            will be downloaded. Defaults to None, meaning all files will be downloaded.

        Returns:
            None

        Raises:
            OneDriveClientException: If an error occurs while getting folder contents or downloading a file.
        """

        if not last_modified_at:
            last_modified_at = datetime.strptime("1999-01-01T00:00:00", "%Y-%m-%dT%H:%M:%S")

        folder_path, mask = self.split_path_mask(file_path)
        logging.info(f"Downloading files matching mask {mask} from folder {folder_path}")
        if last_modified_at:
            logging.info(f"The component will fetch files fresher than {last_modified_at}")

        if self.client_type == "Sharepoint":
            items = self.list_folder_contents_sharepoint(folder_path)
        elif self.client_type == "OneDriveForBusiness":
            items = self.list_folder_contents_ofb(folder_path)
        elif self.client_type == "OneDrive":
            items = self.list_folder_contents(folder_path)
        else:
            raise OneDriveClientException(f"Unsupported client type: {self.client_type}")

        for item in items:
            if item.get('file') is not None:
                if fnmatch.fnmatch(item['name'], mask):
                    last_modified = datetime.fromisoformat(item['lastModifiedDateTime'][:-1])
                    self.update_freshest_file_timestamp(last_modified)
                    if last_modified_at and last_modified <= last_modified_at:
                        # skip downloading the file
                        logging.info(
                            f"Skipping file {item['name']} because it was last modified before {last_modified_at}.")
                        continue
                    else:
                        logging.info(f"File {item['name']} will be downloaded.")

                    file_url = item['@microsoft.graph.downloadUrl']
                    output_path = os.path.join(output_dir, item['name'])
                    self.download_file_from_onedrive_url(file_url, output_path, filename=item["name"])

            elif item.get('folder') is not None:
                if folder_path == "/":
                    subfolder_path = f"{folder_path}{item['name']}"
                else:
                    subfolder_path = f"{folder_path}/{item['name']}"
                self.download_files(subfolder_path, output_dir, last_modified_at)

    def list_sharepoint_sites(self):
        sites_url = f"https://graph.microsoft.com/v1.0/{self.tenant_id}/sites?search=*"
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(sites_url, headers=headers)

        if response.status_code == 200:
            sites_data = response.json()['value']
            sites_list = []

            for site in sites_data:
                site_info = {
                    'id': site['id'],
                    'name': site['displayName'],
                    'url': site['webUrl']
                }
                sites_list.append(site_info)

            return sites_list
        else:
            raise Exception(f"Error occurred when fetching SharePoint sites: {response.status_code}, {response.text}")

    @staticmethod
    def split_path_mask(file_path):
        # Normalize the path to handle platform differences
        file_path = os.path.normpath(file_path)
        components = file_path.split(os.sep)

        path = ""
        mask = ""

        for i, component in enumerate(components):
            if "*" in component:
                mask = os.sep.join(components[i:])
                break
            else:
                path = os.path.join(path, component)

        # If mask is empty, set it to "*"
        if not mask:
            mask = "*"

        # If path is empty or doesn't end with a separator, add one
        if not path or path[-1] != os.sep:
            path += os.sep

        return path, mask

    @property
    def get_freshest_file_timestamp(self):
        return self.freshest_file_timestamp

    def update_freshest_file_timestamp(self, last_modified):
        if not self.freshest_file_timestamp or last_modified > self.freshest_file_timestamp:
            self.freshest_file_timestamp = last_modified

    @staticmethod
    def _parse_response(response, endpoint):
        status_code = response.status_code
        if 'application/json' in response.headers['Content-Type']:
            r = response.json()
        else:
            r = response.text
        if status_code in (200, 201, 202):
            return r
        elif status_code == 204:
            return None
        elif status_code == 400:
            raise exceptions.BadRequest(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 401:
            raise exceptions.Unauthorized(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 403:
            raise exceptions.Forbidden(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 404:
            raise exceptions.NotFound(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 405:
            raise exceptions.MethodNotAllowed(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 406:
            raise exceptions.NotAcceptable(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 409:
            raise exceptions.Conflict(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 410:
            raise exceptions.Gone(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 411:
            raise exceptions.LengthRequired(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 412:
            raise exceptions.PreconditionFailed(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 413:
            raise exceptions.RequestEntityTooLarge(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 415:
            raise exceptions.UnsupportedMediaType(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 416:
            raise exceptions.RequestedRangeNotSatisfiable(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 422:
            raise exceptions.UnprocessableEntity(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 429:
            raise exceptions.TooManyRequests(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 500:
            raise exceptions.InternalServerError(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 501:
            raise exceptions.NotImplemented(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 503:
            raise exceptions.ServiceUnavailable(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 504:
            raise exceptions.GatewayTimeout(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 507:
            raise exceptions.InsufficientStorage(f'Calling endpoint {endpoint} failed', r)
        elif status_code == 509:
            raise exceptions.BandwidthLimitExceeded(f'Calling endpoint {endpoint} failed', r)
        else:
            raise exceptions.UnknownError(f'Calling endpoint {endpoint} failed', r)
