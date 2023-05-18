import requests
import logging
import fnmatch
import os
from datetime import datetime
import backoff
from urllib.parse import urlparse
from requests.exceptions import HTTPError

from keboola.http_client import HttpClient

from . import exceptions


class OneDriveClientException(Exception):
    pass


class OneDriveClient(HttpClient):
    """
    The OneDriveClient class manages the interaction with OneDrive API. It handles tasks such as
    authenticating the client, configuring the client type (OneDrive, SharePoint, or OneDrive for Business),
    and managing file downloads. Currently, there is a limit to runtime of 60 minutes, because of expiration
    of access_token.

    Parameters:
    ----------
    refresh_token : str
        The token used to refresh the client's access to the OneDrive API.
    files_out_folder : str
        The directory path where downloaded files will be stored.
    client_id : str
        The ID assigned to the client by the OneDrive API.
    client_secret : str
        The secret key assigned to the client by the OneDrive API.
    tenant_id : str, optional
        The ID of the tenant, if the client is a business account (default is None).
    site_url : str, optional
        The URL of the SharePoint site, if the client is configured for SharePoint (default is None).
    """
    MAX_RETRIES = 5

    def __init__(self, refresh_token, files_out_folder, client_id, client_secret, tenant_id=None, site_url=None):

        self.base_url = ""
        self.files_out_folder = files_out_folder
        self.refresh_token = refresh_token

        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.site_url = site_url
        self.access_token = ""
        self.auth_header = {}

        self.client_type, self.authority, self.scope = self._configure_client()

        if not self.access_token or not self.auth_header:
            self._get_access_token()
            self.auth_header = {"Authorization": 'Bearer ' + self.access_token, "Content-Type": "application/json"}

        self.downloaded_files = []
        self.freshest_file_timestamp = None
        self.file_mask = None

        super().__init__(base_url=self.base_url, max_retries=self.MAX_RETRIES, backoff_factor=0.3,
                         auth_header=self.auth_header, status_forcelist=(429, 503, 500, 502, 504))

    def _configure_client(self):
        if not self.tenant_id and not self.site_url:
            return self._configure_onedrive_client()
        elif self.tenant_id and self.site_url:
            return self._configure_sharepoint_client()
        elif self.tenant_id and not self.site_url:
            return self._configure_onedrive_for_business_client()
        else:
            raise OneDriveClientException(f"Unsupported settings: {self.tenant_id}, {self.site_url}")

    def _configure_onedrive_client(self):
        logging.info("Initializing OneDrive client")
        client_type = "OneDrive"
        authority = 'https://login.microsoftonline.com/common'
        self.base_url = 'https://graph.microsoft.com/v1.0/me'
        scope = ['https://graph.microsoft.com/User.Read', 'https://graph.microsoft.com/Files.Read.All']
        return client_type, authority, scope

    def _configure_sharepoint_client(self):
        logging.info("Initializing Sharepoint client")
        client_type = "Sharepoint"
        authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        # We need access token to get site id and url
        self.base_url = 'https://graph.microsoft.com/v1.0/sites/'
        self._get_access_token()
        site_id = self.get_site_id_from_url(self.site_url)
        self.base_url = self.base_url + site_id
        return client_type, authority, self.scope

    def _configure_onedrive_for_business_client(self):
        logging.info("Initializing OneDriveForBusiness client")
        client_type = "OneDriveForBusiness"
        authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.base_url = 'https://graph.microsoft.com/v1.0/me/drive'
        scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        return client_type, authority, scope

    def _get_access_token(self) -> None:
        """
        This is handled using requests to handle compatibility with OneDrive and Sharepoint client.
        """
        if self.access_token:
            headers = {'Authorization': f'Bearer {self.access_token}'}
            response = requests.get(self.base_url, headers=headers)
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
            "refresh_token": self.refresh_token,
        }

        response = requests.post(url=request_url, headers=headers, data=payload)

        token = response.json().get("access_token", None)
        if not token:
            logging.error(response.json())
            raise OneDriveClientException("Authentication failed, "
                                          "reauthorize the extractor in extractor configuration.")
        logging.info("Access token fetched")
        self.access_token = response.json()["access_token"]

    def get_request(self, url: str, is_absolute_path: bool, stream: bool = False):
        response = self.get_raw(url, is_absolute_path=is_absolute_path, stream=stream)
        if response.status_code == 200:
            return response
        elif response.status_code == 401:
            self._get_access_token()
            return self.get_request(url, is_absolute_path, stream)
        else:
            raise OneDriveClientException(f"Cannot fetch {url}, "
                                          f"response: {response.text}, "
                                          f"status_code: {response.status_code}")

    def _list_folder_contents(self, drive_type: str, folder_path=None):
        if folder_path is None or folder_path == '/':
            folder_id = 'root'
        else:
            # Resolve the path to a folder id
            drive_root = f"{self.base_url}/{drive_type if drive_type == 'ofb' else 'drive/root'}"
            url = f"{drive_root}:/{folder_path.lstrip('/')}:/"
            response = self.get_request(url, is_absolute_path=True)
            if response.status_code == 200:
                folder_id = response.json()['id']
            else:
                raise OneDriveClientException(f"Error resolving folder path '{folder_path}': "
                                              f"{response.status_code}, {response.text}")

        if folder_id == 'root':
            root_or_drive = 'drive/root' if drive_type != 'ofb' else drive_type
            folder_path = f"{self.base_url}/{root_or_drive}/children"
        else:
            drive_or_ofb = 'drive' if drive_type != 'ofb' else drive_type
            folder_path = f"{self.base_url}/{drive_or_ofb}/items/{folder_id}/children"

        response = self.get_request(folder_path, is_absolute_path=True)

        if response.status_code == 200:
            items = response.json()['value']
            return items
        else:
            raise OneDriveClientException(f"Error occurred when getting folder content:"
                                          f" {response.status_code}, {response.text}")

    def _list_folder_contents_sharepoint(self, folder_path=None, library_name=None):
        folder_id = 'root' if folder_path is None or folder_path == '/' else None
        if library_name:
            logging.info(f"The component will try to fetch files from library {library_name}")
            library_id = self._get_sharepoint_library_id(library_name)
            library_drive_id = self._get_sharepoint_library_drive_id(library_id)
            if not folder_id:
                folder_id = self._get_folder_id_from_path(library_drive_id, folder_path)
            folder_path = self._get_folder_path(library_drive_id, folder_id)
        else:
            logging.info(f"Scanning folder: {folder_path}")
            if not folder_id:
                folder_id = self._get_folder_id_from_path(self.base_url + '/drive/root', folder_path)
            folder_path = self._get_folder_path(self.base_url + '/drive', folder_id)
        return self._get_folder_contents_sharepoint(folder_path)

    def _get_sharepoint_library_id(self, library_name):
        libraries = self._get_sharepoint_document_libraries()
        library = next((lib for lib in libraries if lib['name'] == library_name), None)
        if library is None:
            raise OneDriveClientException(f"Library '{library_name}' not found")
        return library['id']

    def _get_sharepoint_library_drive_id(self, library_id):
        url = f"{self.base_url}/lists/{library_id}/drive"
        response = self.get_request(url, is_absolute_path=True)
        if response.status_code == 200:
            return response.json()['id']
        else:
            raise OneDriveClientException(f"Error fetching library drive:"
                                          f" {response.status_code}, {response.text}")

    def _get_folder_id_from_path(self, library_drive_id, folder_path):
        url = f"{self.base_url}/drives/{library_drive_id}/root:/{folder_path.strip('/')}"
        response = self.get_request(url, is_absolute_path=True)
        if response.status_code == 200:
            return response.json()['id']
        else:
            raise OneDriveClientException(f"Error resolving folder path '{folder_path}': "
                                          f"{response.status_code}, {response.text}")

    def _get_folder_path(self, library_drive_id, folder_id):
        if folder_id == 'root':
            return f"{self.base_url}/drives/{library_drive_id}/root/children"
        else:
            return f"{self.base_url}/drives/{library_drive_id}/items/{folder_id}/children"

    def _get_folder_contents_sharepoint(self, folder_path):
        response = self.get_request(folder_path, is_absolute_path=True)
        if response.status_code == 200:
            return response.json()['value']
        else:
            raise OneDriveClientException(f"Error occurred when getting folder content:"
                                          f" {response.status_code}, {response.text}")

    def get_site_id_from_url(self, site_url: str):
        parsed_url = urlparse(site_url)
        hostname = parsed_url.netloc
        server_relative_path = parsed_url.path

        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{server_relative_path}"
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            site = response.json()
            site_id = site['id']
            return site_id
        else:
            raise OneDriveClientException(f"Error occurred when fetching site information: "
                                          f"{response.status_code}, {response.text}")

    def _get_sharepoint_document_libraries(self):
        site_id = self.get_site_id_from_url(self.site_url)
        url = f"{self.base_url}/sites/{site_id}/lists"
        response = self.get_request(url, is_absolute_path=True)

        if response.status_code == 200:
            libraries = response.json()['value']
            return libraries
        else:
            raise OneDriveClientException(f"Error occurred when getting SharePoint document libraries:"
                                          f" {response.status_code}, {response.text}")

    @backoff.on_exception(backoff.expo, Exception, max_tries=6)
    def _download_file_from_onedrive_url(self, url, output_path, filename):
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
        response = self.get_request(url, is_absolute_path=True, stream=True)

        try:
            parsed_response = self._parse_response(response, url, filename)
            if parsed_response is not None:
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=32768):
                        f.write(chunk)
                logging.info(f"File {filename} downloaded.")
            else:
                logging.warning(f"No content in the response for file {filename}.")
        except OneDriveClientException as e:
            raise e

        if filename in self.downloaded_files:
            logging.warning(f"File {filename} has the same as an already downloaded file. It will be overwritten.")
        self.downloaded_files.append(filename)

    def _get_items_based_on_client_type(self, folder_path, library_name):
        if self.client_type == "Sharepoint":
            return self._list_folder_contents_sharepoint(folder_path, library_name)
        elif self.client_type == "OneDriveForBusiness":
            return self._list_folder_contents("ofb", folder_path)
        elif self.client_type == "OneDrive":
            return self._list_folder_contents("onedrive", folder_path)
        else:
            raise OneDriveClientException(f"Unsupported client type: {self.client_type}")

    @staticmethod
    def _create_folder_mask(mask, folder_path):
        if "*" in mask and not folder_path == "/":
            return mask.split("*", 1)[0] + "*"
        return None

    def _process_items(self, items, folder_mask, mask, folder_path, output_dir, last_modified_at, library_name):
        for item in items:
            if item.get('folder') is not None:
                self._process_folder_item(item, folder_mask, mask, folder_path, output_dir, last_modified_at,
                                          library_name)
            elif item.get('file') is not None:
                self._process_file_item(item, mask, output_dir, last_modified_at)

    def _process_folder_item(self, item, folder_mask, mask, folder_path, output_dir, last_modified_at, library_name):
        if folder_mask and not fnmatch.fnmatch(item['name'], folder_mask):
            logging.debug(f"Skipping folder {item['name']} because it doesn't match the folder_mask {folder_mask}")
            return
        subfolder_file_path = os.path.join(folder_path, item['name'], os.path.basename(mask))
        self.download_files(subfolder_file_path, output_dir, last_modified_at, library_name)

    def _process_file_item(self, item, mask, output_dir, last_modified_at):
        if mask and not fnmatch.fnmatch(item['name'], mask):
            logging.debug(f"Skipping file {item['name']} because it doesn't match the mask {mask}")
            return
        last_modified = datetime.fromisoformat(item['lastModifiedDateTime'][:-1])
        self._update_freshest_file_timestamp(last_modified)
        if last_modified_at and last_modified <= last_modified_at:
            logging.debug(f"Skipping file {item['name']} because it was last modified before {last_modified_at}.")
            return
        file_url = item['@microsoft.graph.downloadUrl']
        output_path = os.path.join(output_dir, item['name'])
        self._download_file_from_onedrive_url(file_url, output_path, filename=item["name"])

    def get_document_libraries(self, site_url):
        """
        Retrieves a list of document libraries from a site using the Microsoft Graph API.

        :param site_url: The url of the site to retrieve the document libraries from.
        :return: A list of dictionaries containing the document library metadata.
        """
        site_id = self.get_site_id_from_url(site_url)

        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        response = self.get_request(url, is_absolute_path=True)

        try:
            response.raise_for_status()
        except HTTPError as e:
            raise OneDriveClientException(f"Cannot get document libraries for site_url: {site_url}") from e

        return response.json()['value']

    def download_files(self, file_path, output_dir, last_modified_at=None, library_name: str = None):
        if not last_modified_at:
            last_modified_at = datetime.strptime("2000-01-01T00:00:00", "%Y-%m-%dT%H:%M:%S")
        folder_path, mask = self._split_path_mask(file_path)
        logging.info(f"Downloading files matching mask {mask} from folder {folder_path}")
        items = self._get_items_based_on_client_type(folder_path, library_name)
        folder_mask = self._create_folder_mask(mask, folder_path)
        self._process_items(items, folder_mask, mask, folder_path, output_dir, last_modified_at, library_name)

    @property
    def get_freshest_file_timestamp(self):
        return self.freshest_file_timestamp

    @staticmethod
    def _split_path_mask(file_path):
        # Normalize the path to handle platform differences
        file_path = os.path.normpath(file_path)
        components = file_path.split(os.sep)

        path = ""
        mask = ""

        for i, component in enumerate(components):
            if "*" in component:
                mask = os.sep.join(components[i:])
                break
            elif i == len(components) - 1 and "." in component:
                mask = component
            else:
                path = os.path.join(path, component)

        # If mask is empty, set it to "*"
        if not mask:
            mask = "*"

        # If path is empty or doesn't end with a separator, add one
        if not path or path[-1] != os.sep:
            path += os.sep

        return path, mask

    def _update_freshest_file_timestamp(self, last_modified):
        if not self.freshest_file_timestamp or last_modified > self.freshest_file_timestamp:
            self.freshest_file_timestamp = last_modified

    @staticmethod
    def _parse_response(response, endpoint, filename):
        content_type = response.headers['Content-Type']

        try:
            result = response.json() if 'application/json' in content_type else response.text
        except requests.exceptions.JSONDecodeError:
            logging.error(f"Unable to parse JSON from response for {filename}.")
            result = response.text  # Fallback to treating it as text or handle as you see fit

        status_exceptions = {
            400: exceptions.BadRequest,
            401: exceptions.Unauthorized,
            403: exceptions.Forbidden,
            404: exceptions.NotFound,
            405: exceptions.MethodNotAllowed,
            406: exceptions.NotAcceptable,
            409: exceptions.Conflict,
            410: exceptions.Gone,
            411: exceptions.LengthRequired,
            412: exceptions.PreconditionFailed,
            413: exceptions.RequestEntityTooLarge,
            415: exceptions.UnsupportedMediaType,
            416: exceptions.RequestedRangeNotSatisfiable,
            422: exceptions.UnprocessableEntity,
            429: exceptions.TooManyRequests,
            500: exceptions.InternalServerError,
            501: exceptions.NotImplemented,
            503: exceptions.ServiceUnavailable,
            504: exceptions.GatewayTimeout,
            507: exceptions.InsufficientStorage,
            509: exceptions.BandwidthLimitExceeded,
        }

        if response.status_code in (200, 201, 202):
            return result
        elif response.status_code == 204:
            return None
        elif response.status_code in status_exceptions:
            raise status_exceptions[response.status_code](f'Calling endpoint {endpoint} failed', result)
        else:
            raise exceptions.UnknownError(f'Calling endpoint {endpoint} failed', result)
