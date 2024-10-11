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
        self._refresh_token = refresh_token

        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.site_url = site_url
        self.access_token = ""

        self.client_type, self.authority, self.scope = self._configure_client()

        if not self.access_token:
            self._get_request_tokens()

        self.downloaded_files = []
        self.freshest_file_timestamp = None
        self.file_mask = None

        super().__init__(base_url=self.base_url, max_retries=self.MAX_RETRIES, backoff_factor=0.3,
                         status_forcelist=(429, 503, 500, 502, 504))

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
        scope = ['https://graph.microsoft.com/User.Read', 'https://graph.microsoft.com/Files.Read.All',
                 'https://graph.microsoft.com/wl.offline_access']
        return client_type, authority, scope

    def _configure_sharepoint_client(self):
        logging.info("Initializing Sharepoint client")
        client_type = "Sharepoint"
        authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.scope = 'https://graph.microsoft.com/Sites.Read.All https://graph.microsoft.com/Files.Read.All'
        # We need access token to get site id and url
        self.base_url = 'https://graph.microsoft.com/v1.0/sites/'
        self._get_request_tokens()
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

    def _get_request_tokens(self) -> None:
        """
        This is handled using requests to handle compatibility with OneDrive and Sharepoint client.
        """
        logging.info("Fetching New Access token")
        request_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.scope,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        response = requests.post(url=request_url, headers=headers, data=payload)

        token = response.json().get("access_token", None)
        if not token:
            logging.error(response.json())
            raise OneDriveClientException("Authentication failed, "
                                          "reauthorize the extractor in extractor configuration.")
        logging.info("New Access token fetched.")
        self.access_token = response.json()["access_token"]
        logging.debug(response.json())
        self._refresh_token = response.json()["refresh_token"]

        new_header = {"Authorization": 'Bearer ' + self.access_token, "Content-Type": "application/json"}
        self.update_auth_header(updated_header=new_header, overwrite=True)

    @property
    def refresh_token(self):
        return self._refresh_token

    def get_request(self, url: str, is_absolute_path: bool, stream: bool = False):
        response = self.get_raw(url, is_absolute_path=is_absolute_path, stream=stream)
        if response.status_code == 200:
            return response
        elif response.status_code == 401:
            self._get_request_tokens()
            return self.get_request(url, is_absolute_path, stream)
        elif response.status_code == 404:
            logging.error(f"Url {url} returned 404.")
            return None
        else:
            raise OneDriveClientException(f"Cannot fetch {url}, "
                                          f"response: {response.text}, "
                                          f"status_code: {response.status_code}")

    def _resolve_folder_id(self, drive_type: str, folder_path: str):
        if folder_path is None or folder_path == '/':
            return 'root'

        drive_root = f"{self.base_url}/{'root' if drive_type == 'ofb' else 'drive/root'}"
        url = f"{drive_root}:/{folder_path.strip('/')}:/"
        response = self.get_request(url, is_absolute_path=True)

        if response:
            if response.status_code == 200:
                return response.json()['id']
            else:
                raise OneDriveClientException(f"Error resolving folder path '{folder_path}': "
                                              f"{response.status_code}, {response.text}")
        else:
            raise OneDriveClientException(f"Cannot find {folder_path}. Please verify if this path exists.")

    def _get_folder_contents_onedrive(self, drive_type: str, folder_id: str):
        if folder_id == 'root':
            root_or_drive = 'drive/root' if drive_type != 'ofb' else 'root'
            folder_url = f"{self.base_url}/{root_or_drive}/children"
        else:
            drive_or_ofb = 'drive' if drive_type != 'ofb' else ''
            folder_url = f"{self.base_url}/{drive_or_ofb}/items/{folder_id}/children"

        return self._get_folder_content(folder_url)

    def _list_folder_contents(self, drive_type: str, folder_path=None):
        folder_id = self._resolve_folder_id(drive_type, folder_path)
        return self._get_folder_contents_onedrive(drive_type, folder_id)

    def _get_folder_contents_sharepoint(self, folder_path=None, library_name=None):
        folder_id = 'root' if folder_path is None or folder_path == '/' else None

        if library_name:
            logging.info(f"The component will try to fetch files from library {library_name}")
            library_id = self._get_sharepoint_library_id(library_name)
            library_drive_id = self._get_sharepoint_library_drive_id(library_id)
            if not folder_id:
                folder_id = self._get_sharepoint_folder_id_from_path(library_drive_id, folder_path)
            folder_path = self._make_library_folder_path(folder_id, library_drive_id)
        else:
            logging.info(f"Scanning folder: {folder_path}")
            if folder_id == "root":
                folder_path = f"{self.base_url}/drive/root/children"
            else:
                folder_path = f"{self.base_url}/drive/root:/{folder_path}"
                folder_id = self._get_sharepoint_folder_id_from_path("", folder_path)
                folder_path = f"{self.base_url}/drive/items/{folder_id}/children"

            logging.debug(f"Folder path set to: {folder_path}")

        folder_content = self._get_folder_content(folder_path)

        return folder_content

    def _get_folder_content(self, folder_url: str) -> list:
        folder_content = []
        while True:
            response = self.get_request(folder_url, is_absolute_path=True)

            if response.status_code == 200:
                folder_content.extend(response.json()['value'])
            else:
                raise OneDriveClientException(f"Error occurred when getting folder content:"
                                              f" {response.status_code}, {response.text}")

            if response.json().get('@odata.nextLink'):
                folder_url = response.json().get('@odata.nextLink')
            else:
                return folder_content

    def _get_sharepoint_folder_id_from_path(self, library_drive_id, folder_path):
        if library_drive_id:
            url = f"{self.base_url}/drives/{library_drive_id}/root:/{folder_path.strip('/')}"
        else:
            url = folder_path

        response = self.get_request(url, is_absolute_path=True)
        if response and response.status_code == 200:
            return response.json()['id']

        error_message = f"Error resolving folder path '{folder_path}': {response.status_code}, {response.text}" \
            if response else f"Error resolving folder path '{folder_path}': No response received"
        raise OneDriveClientException(error_message)

    def _get_sharepoint_library_id(self, library_name):
        libraries = self._get_sharepoint_document_libraries()
        library = next((lib for lib in libraries if lib['name'] == library_name), None)
        if library is None:
            raise OneDriveClientException(f"Library '{library_name}' not found")
        return library['id']

    def _get_sharepoint_library_drive_id(self, library_id):
        url = f"{self.base_url}/lists/{library_id}/drive"
        response = self.get_request(url, is_absolute_path=True)

        if response and response.status_code == 200:
            return response.json()['id']

        error_message = f"Error fetching library drive: {response.status_code}, {response.text}" \
            if response else "Error fetching library drive: No response received"
        raise OneDriveClientException(error_message)

    def _make_library_folder_path(self, folder_id, library_drive_id: str = ""):
        if folder_id == 'root':
            return f"{self.base_url}/drives/{library_drive_id}/root/children"
        else:
            return f"{self.base_url}/drives/{library_drive_id}/items/{folder_id}/children"

    def get_site_id_from_url(self, site_url: str):
        parsed_url = urlparse(site_url)
        hostname = parsed_url.netloc
        server_relative_path = parsed_url.path

        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{server_relative_path}"
        headers = {"Authorization": 'Bearer ' + self.access_token}

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

    @backoff.on_exception(backoff.expo, Exception, max_tries=MAX_RETRIES)
    def _download_file_from_onedrive_url(self, url, output_path, filename):
        """
        Downloads a file from OneDrive using the provided download URL and saves it to the specified output path.
        """
        with self.get_request(url, is_absolute_path=True, stream=True) as r:

            if r is None:
                self._handle_no_response(filename)
                return

            if r.status_code != 200:
                self._handle_invalid_status_code(r.status_code, filename)
                return

            try:
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

                logging.info(f"File {filename} downloaded.")
            except OneDriveClientException as e:
                raise e

        self._handle_existing_file(filename)

    @staticmethod
    def _handle_no_response(filename):
        logging.error(f"Cannot download file {filename}, got no response from OneDrive API.")

    @staticmethod
    def _handle_invalid_status_code(status_code, filename):
        logging.error(f"Cannot download file {filename}, received {status_code} from OneDrive API.")

    def _handle_existing_file(self, filename):
        if filename in self.downloaded_files:
            logging.warning(f"File {filename} has the same filename as an already downloaded file. "
                            f"It has been overwritten.")
        self.downloaded_files.append(filename)

    def _get_items_based_on_client_type(self, folder_path, library_name):
        if self.client_type == "Sharepoint":
            return self._get_folder_contents_sharepoint(folder_path, library_name)
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

        Args:
            site_url (str): The URL of the site to retrieve the document libraries from.

        Returns:
            list: A list of dictionaries containing the document library metadata.

        Raises:
            OneDriveClientException: If an error occurs while retrieving the document libraries.
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
            raise OneDriveClientException(f'Calling endpoint {endpoint} failed: {result}') from status_exceptions[
                response.status_code]
        else:
            raise OneDriveClientException(f'Calling endpoint {endpoint} failed: {result}') from exceptions.UnknownError
