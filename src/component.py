import logging
from datetime import datetime
from typing import List, Union, Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client.client import OneDriveClient, OneDriveClientException
from configuration import Configuration, Account
from client.exceptions import BadRequest

KEY_STATE_REFRESH_TOKEN = "#refresh_token"


class Component(ComponentBase):

    def __init__(self):
        super().__init__()
        self._configuration: Configuration

        self.refresh_token = self.configuration.oauth_credentials.data["refresh_token"]
        self.client_id = self.configuration.oauth_credentials.appKey
        self.client_secret = self.configuration.oauth_credentials.appSecret

    def run(self):
        self._init_configuration()
        state_file = self.get_state_file()

        file_path = self._configuration.settings.file_path

        if not file_path:
            file_path = "*"
            logging.warning("File path is not set, the component will try to download everything "
                            "from authorized drive!")

        library_name = self._configuration.account.library_name

        last_modified_at = self._set_last_modified(state_file)

        client = self._get_client(self._configuration.account)

        try:
            client.download_files(file_path=file_path, output_dir=self.files_out_path,
                                  last_modified_at=last_modified_at, library_name=library_name)
        except OneDriveClientException as e:
            raise UserException(e) from e

        self._create_manifests(client)
        self._save_timestamp(client, file_path)

    def _save_timestamp(self, client, file_path) -> None:
        if client.freshest_file_timestamp:
            freshest_timestamp = client.freshest_file_timestamp.isoformat()
            self._save_to_state({"last_modified": freshest_timestamp})
            logging.info(f"Saving freshest file timestamp to statefile: {freshest_timestamp}")
        else:
            logging.warning(f"The component has not found any files matching filename: {file_path}")

    def _create_manifests(self, client) -> None:

        tag = self._configuration.destination.custom_tag
        tags = [tag] if tag else []

        permanent = self._configuration.destination.permanent
        if permanent:
            logging.info("Downloaded files will be stored as permanent files.")

        for filename in client.downloaded_files:
            file_def = self.create_out_file_definition(filename, tags=tags, is_permanent=permanent)
            self.write_manifest(file_def)

    def _set_last_modified(self, state_file) -> Union[str, Any]:
        get_new_only = self._configuration.settings.new_files_only
        last_modified_at = False
        if get_new_only:
            if state_file.get("last_modified", False):
                last_modified_at = datetime.fromisoformat(state_file.get("last_modified"))
                logging.info(f"Component will download files with lastModifiedDateTime > {last_modified_at}")
            else:
                logging.warning("last_modified timestamp not found in statefile, Cannot download new files only. "
                                "To resolve this, disable this option in row config or "
                                "set last_modified in statefile manually.")
        return last_modified_at

    def _init_configuration(self) -> None:
        self.validate_configuration_parameters(Configuration.get_dataclass_required_parameters())
        self._configuration: Configuration = Configuration.load_from_dict(self.configuration.parameters)

    def _get_client(self, account_params: Account) -> OneDriveClient:
        tenant_id = account_params.tenant_id
        site_url = account_params.site_url
        for refresh_token in self._get_refresh_tokens():
            try:
                client = OneDriveClient(refresh_token=refresh_token, files_out_folder=self.files_out_path,
                                        client_id=self.client_id, client_secret=self.client_secret,
                                        tenant_id=tenant_id, site_url=site_url)
                self._save_refresh_token_state(client.refresh_token)
                return client
            except BadRequest as e:
                logging.exception(f"Refresh token failed, retrying connection with new refresh token. {e}")
                pass
            except OneDriveClientException as e:
                raise UserException(e) from e
        raise UserException('Authentication failed, reauthorize the extractor in extractor configuration!')

    def _get_refresh_tokens(self) -> list[str]:
        state_file = self.get_state_file()
        state_refresh_token = state_file.get(self.configuration.oauth_credentials.id, {}).get(KEY_STATE_REFRESH_TOKEN)
        return [token for token in [self.refresh_token, state_refresh_token] if token]

    def _save_refresh_token_state(self, new_refresh_token):
        self._save_to_state(
            {self.configuration.oauth_credentials.id: {KEY_STATE_REFRESH_TOKEN: new_refresh_token}})

    def _save_to_state(self, data: dict) -> None:
        actual_data = self.get_state_file()
        new_data = {**actual_data, **data}
        self.write_state_file(new_data)

    @sync_action("listLibraries")
    def list_sharepoint_libraries(self) -> List[SelectElement]:
        account_json = self.configuration.parameters.get("account", {})
        required_parameters = ["tenant_id", "site_url"]
        self._validate_parameters(account_json, required_parameters, 'Credentials')

        acc_config = Account.load_from_dict(account_json)

        client = self._get_client(acc_config)

        libraries = client.get_document_libraries(acc_config.site_url)

        return [
            SelectElement(
                label=library['name'],
                value="Shared Documents" if library['name'] == "Documents" else library['webUrl'].split("/")[-1]
            )
            for library in libraries
        ]


# Main entrypoint
if __name__ == "__main__":
    try:
        comp = Component()
        comp.execute_action()
    except UserException as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
