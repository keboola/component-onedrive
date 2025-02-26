Configuration
=============

- **account_type**: Account type. Determines which configuration fields are displayed for different account types.
- **tenant_id**: Tenant ID required for OneDrive for Business and SharePoint. You can find the Tenant ID in the Azure Portal under **Azure Active Directory** → **Tenant information**.
- **site_url**: Site URL (required only for SharePoint). You can find the site name in the URL address when visiting SharePoint online.
- **library_name**: Library name (optional). Specifies the Document Library from which you want to download files. If you do not wish to download files from a Document Library, leave this field empty.
- **file_path**: Path to the file(s) you want to download from the selected service. Supports wildcards.
     - Examples: 
       - `\*.csv` - Downloads all available CSV files.
       - `/reports/\*.csv` - Downloads all available CSV files from the reports folder and its subfolders.
       - `db_exports/report_\*.xlsx` - Downloads all .xlsx files with names matching report_\* (\* is wildcard) from the db_exports folder and its subfolders. 
       - `db_exports/2022_\*/\*.csv` - Downloads all CSV files from folders matching db_exports/2022_\* (\* is wildcard). 
- **new_files_only**: New Files Only (optional). If set to `true`, the component will use the timestamp of the newest file downloaded in the last run and download only newer files. The `LastModifiedAt` value from GraphAPI is used.
- **custom_tag**: Custom Tag (optional). Adds a custom tag to Keboola Storage for all downloaded files. Only one custom tag is supported.
- **permanent**: Permanent Files (optional). If set to `true`, downloaded files will be stored permanently in Keboola Storage. Otherwise, they will be deleted after 14 days.
