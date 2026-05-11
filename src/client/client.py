import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote, urlparse

import requests
from requests.exceptions import HTTPError

from keboola.http_client import HttpClient

from . import exceptions
from .async_engine import AsyncDriveEngine


class OneDriveClientException(Exception):
    pass


class OneDriveClient(HttpClient):
    """OneDrive / OneDrive for Business / SharePoint client.

    The download path is async (aiohttp) and enumerates the drive via Microsoft Graph
    `/delta`, which streams the whole subtree in flat pages of up to 999 items and
    supports incremental sync via a delta token URL. The sync helpers below are still
    used for the `listLibraries` sync action and for one-shot drive/folder resolution.
    """

    MAX_RETRIES = 5
    TOKEN_REFRESH_LEEWAY_SECONDS = 300

    def __init__(self, refresh_token, files_out_folder, client_id, client_secret,
                 tenant_id=None, site_url=None):
        self.base_url = ""
        self.access_token = ""
        self._access_token_expiry: float = 0.0

        super().__init__(base_url=self.base_url, max_retries=self.MAX_RETRIES, backoff_factor=0.3,
                         status_forcelist=(429, 503, 500, 502, 504))

        self.files_out_folder = files_out_folder
        self._refresh_token = refresh_token

        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.site_url = site_url
        self._configure_client()

        self.downloaded_files: list[str] = []
        self.freshest_file_timestamp: Optional[datetime] = None
        self.new_delta_token_url: Optional[str] = None
        self._drive_id: Optional[str] = None

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
        self.client_type = "OneDrive"
        self.authority = 'https://login.microsoftonline.com/common'
        self.base_url = 'https://graph.microsoft.com/v1.0/me'
        self.scope = 'User.Read Files.Read.All offline_access'
        self._get_request_tokens()

    def _configure_sharepoint_client(self):
        logging.info("Initializing Sharepoint client")
        self.client_type = "Sharepoint"
        self.authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.scope = 'Sites.Read.All Files.Read.All offline_access'
        self.base_url = 'https://graph.microsoft.com/v1.0/sites/'
        self._get_request_tokens()
        site_id = self.get_site_id_from_url(self.site_url)
        self.base_url = self.base_url + site_id

    def _configure_onedrive_for_business_client(self):
        logging.info("Initializing OneDriveForBusiness client")
        self.client_type = "OneDriveForBusiness"
        self.authority = f'https://login.microsoftonline.com/{self.tenant_id}'
        self.base_url = 'https://graph.microsoft.com/v1.0/me/drive'
        self.scope = 'Sites.Read.All Files.Read.All offline_access'
        self._get_request_tokens()

    def _get_request_tokens(self) -> None:
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
        body = response.json()
        token = body.get("access_token")
        if not token:
            logging.error(body)
            raise OneDriveClientException("Authentication failed, "
                                          "reauthorize the extractor in extractor configuration.")

        expires_in = int(body.get("expires_in", 3600))
        self._access_token_expiry = time.monotonic() + expires_in

        logging.info("New Access token fetched (expires in %ss).", expires_in)
        self.access_token = token
        self._refresh_token = body["refresh_token"]

        new_header = {"Authorization": 'Bearer ' + self.access_token, "Content-Type": "application/json"}
        self.update_auth_header(updated_header=new_header, overwrite=True)

    def _ensure_token_fresh(self) -> None:
        if time.monotonic() + self.TOKEN_REFRESH_LEEWAY_SECONDS >= self._access_token_expiry:
            logging.info("Access token close to expiry; refreshing proactively.")
            self._get_request_tokens()

    @property
    def refresh_token(self):
        return self._refresh_token

    def get_request(self, url: str, is_absolute_path: bool, stream: bool = False):
        self._ensure_token_fresh()
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

    # ---------------------------------------------------------------- drive resolution

    def _resolve_drive_id(self, library_name: str = None) -> str:
        if self.client_type == "Sharepoint":
            if library_name:
                library_id = self._get_sharepoint_library_id(library_name)
                return self._get_sharepoint_library_drive_id(library_id)
            url = f"{self.base_url}/drive"
        else:
            url = f"{self.base_url}/drive" if self.client_type == "OneDrive" else self.base_url
        response = self.get_request(url, is_absolute_path=True)
        if not response or response.status_code != 200:
            raise OneDriveClientException(f"Cannot resolve drive id via {url}")
        try:
            return response.json()['id']
        except KeyError as err:
            raise OneDriveClientException(f"Drive response missing id: {response.json()}") from err

    def _resolve_scope_folder_id(self, drive_id: str, folder_path: str) -> str:
        normalized = (folder_path or "").strip("/").strip()
        if not normalized:
            return "root"
        encoded = quote(normalized, safe="/")
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded}:/"
        response = self.get_request(url, is_absolute_path=True)
        if response is None:
            raise OneDriveClientException(
                f"Cannot find folder '{folder_path}'. Please verify if this path exists."
            )
        if response.status_code != 200:
            raise OneDriveClientException(
                f"Error resolving folder path '{folder_path}': {response.status_code}, {response.text}"
            )
        return response.json()['id']

    # ---------------------------------------------------------------- sharepoint helpers

    def _get_sharepoint_library_id(self, library_name):
        libraries = self._get_sharepoint_document_libraries()
        logging.debug(f"Found libraries: {libraries}")
        library = next((lib for lib in libraries if lib['name'] == library_name), None)
        if library is None:
            library = next((lib for lib in libraries if lib['webUrl'].split("/")[-1] == library_name), None)
        if library is None:
            raise OneDriveClientException(f"Library '{library_name}' not found")
        return library['id']

    def _get_sharepoint_library_drive_id(self, library_id):
        url = f"{self.base_url}/lists/{library_id}/drive"
        response = self.get_request(url, is_absolute_path=True)
        if response and response.status_code == 200:
            try:
                return response.json()['id']
            except KeyError:
                raise OneDriveClientException(f"Error fetching library drive: {response.json()}")
        error_message = (
            f"Error fetching library drive: {response.status_code}, {response.text}"
            if response else "Error fetching library drive: No response received"
        )
        raise OneDriveClientException(error_message)

    def get_site_id_from_url(self, site_url: str):
        parsed_url = urlparse(site_url)
        hostname = parsed_url.netloc
        server_relative_path = parsed_url.path

        url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{server_relative_path}"
        headers = {"Authorization": 'Bearer ' + self.access_token}

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()['id']
        raise OneDriveClientException(
            f"Error occurred when fetching site information: {response.status_code}, {response.text}"
        )

    def _get_sharepoint_document_libraries(self):
        site_id = self.get_site_id_from_url(self.site_url)
        url = f"{self.base_url}/sites/{site_id}/lists"
        response = self.get_request(url, is_absolute_path=True)
        if response.status_code == 200:
            return response.json()['value']
        raise OneDriveClientException(
            f"Error occurred when getting SharePoint document libraries: "
            f"{response.status_code}, {response.text}"
        )

    def get_document_libraries(self, site_url):
        """Returns document libraries for a SharePoint site. Used by sync action."""
        site_id = self.get_site_id_from_url(site_url)
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives"
        response = self.get_request(url, is_absolute_path=True)
        try:
            response.raise_for_status()
        except HTTPError as e:
            raise OneDriveClientException(f"Cannot get document libraries for site_url: {site_url}") from e
        return response.json()['value']

    # ---------------------------------------------------------------- public download API

    def download_files(self, file_path, output_dir, last_modified_at=None,
                       library_name: str = None, delta_token_url: Optional[str] = None) -> None:
        folder_path, mask = self._split_path_mask(file_path)
        logging.info(
            "Downloading files matching mask '%s' from folder '%s' (delta_token=%s).",
            mask, folder_path or "/", "present" if delta_token_url else "absent",
        )

        if last_modified_at is False:
            last_modified_at = None

        if self._drive_id is None:
            self._drive_id = self._resolve_drive_id(library_name)
            logging.info("Resolved drive id: %s", self._drive_id)

        scope_folder_id = "root"
        if not delta_token_url:
            scope_folder_id = self._resolve_scope_folder_id(self._drive_id, folder_path)

        engine = AsyncDriveEngine(
            drive_id=self._drive_id,
            scope_folder_id=scope_folder_id,
            scope_folder_path=folder_path,
            mask=mask,
            output_dir=output_dir,
            last_modified_at=last_modified_at,
            delta_token_url=delta_token_url,
            token_provider=self._async_token_provider,
        )

        try:
            asyncio.run(engine.run())
        except Exception as err:
            raise OneDriveClientException(str(err)) from err

        self.downloaded_files = engine.downloaded_files
        self.freshest_file_timestamp = engine.freshest_file_timestamp
        self.new_delta_token_url = engine.new_delta_token_url

    async def _async_token_provider(self, force_refresh: bool) -> str:
        if force_refresh:
            await asyncio.to_thread(self._get_request_tokens)
        else:
            await asyncio.to_thread(self._ensure_token_fresh)
        return self.access_token

    @property
    def get_freshest_file_timestamp(self):
        return self.freshest_file_timestamp

    @staticmethod
    def _split_path_mask(file_path):
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

        if not mask:
            mask = "*"

        if not path or path[-1] != os.sep:
            path += os.sep

        return path, mask

    @staticmethod
    def _parse_response(response, endpoint, filename):
        content_type = response.headers['Content-Type']
        try:
            result = response.json() if 'application/json' in content_type else response.text
        except requests.exceptions.JSONDecodeError:
            logging.error(f"Unable to parse JSON from response for {filename}.")
            result = response.text

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
            raise OneDriveClientException(
                f'Calling endpoint {endpoint} failed: {result}'
            ) from status_exceptions[response.status_code]
        else:
            raise OneDriveClientException(
                f'Calling endpoint {endpoint} failed: {result}'
            ) from exceptions.UnknownError
