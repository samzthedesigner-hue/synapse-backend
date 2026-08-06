import json
import os
import tempfile
import logging
from datetime import datetime
from config import Config
from database.models import get_connection

logger = logging.getLogger(__name__)

def backup_to_drive():
    if not Config.GOOGLE_DRIVE_ENABLED:
        logger.info("Google Drive backup disabled")
        return False

    try:
        from database.store import DataStore
        store = DataStore()
        data = store.get_all_for_backup()

        backup_data = {
            'version': '1.0',
            'timestamp': datetime.now().isoformat(),
            'items': data,
            'total_items': len(data)
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(backup_data, f)
            temp_path = f.name

        if Config.GOOGLE_DRIVE_CREDENTIALS:
            _upload_to_drive(temp_path, f"synapse_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        os.unlink(temp_path)
        _log_backup('success', len(data), os.path.getsize(temp_path))

        logger.info(f"Backed up {len(data)} items to Google Drive")
        return True

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        _log_backup('failed', 0, 0, str(e))
        return False

def restore_from_drive():
    if not Config.GOOGLE_DRIVE_ENABLED:
        logger.info("Google Drive restore disabled")
        return False

    try:
        latest_backup = _find_latest_backup()

        if not latest_backup:
            logger.info("No backup found in Google Drive")
            return False

        backup_data = _download_from_drive(latest_backup)

        if not backup_data:
            return False

        from database.store import DataStore
        store = DataStore()
        count = store.restore_from_backup(backup_data.get('items', []))

        logger.info(f"Restored {count} items from Google Drive backup")
        return True

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return False

def _upload_to_drive(file_path, file_name):
    try:
        import base64
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        creds_json = base64.b64decode(Config.GOOGLE_DRIVE_CREDENTIALS).decode('utf-8')
        creds_dict = json.loads(creds_json)

        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )

        service = build('drive', 'v3', credentials=credentials)

        file_metadata = {
            'name': file_name,
            'parents': [Config.GOOGLE_DRIVE_FOLDER_ID] if Config.GOOGLE_DRIVE_FOLDER_ID else []
        }

        media = MediaFileUpload(file_path, mimetype='application/json')

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        logger.info(f"Uploaded backup to Drive: {file.get('id')}")
        _clean_old_backups(service)

    except ImportError:
        logger.warning("Google Drive libraries not installed. Skipping upload.")
    except Exception as e:
        logger.error(f"Drive upload failed: {e}")

def _find_latest_backup():
    try:
        import base64
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_json = base64.b64decode(Config.GOOGLE_DRIVE_CREDENTIALS).decode('utf-8')
        creds_dict = json.loads(creds_json)

        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )

        service = build('drive', 'v3', credentials=credentials)

        query = "name contains 'synapse_backup'"
        if Config.GOOGLE_DRIVE_FOLDER_ID:
            query += f" and '{Config.GOOGLE_DRIVE_FOLDER_ID}' in parents"

        results = service.files().list(
            q=query,
            orderBy='createdTime desc',
            pageSize=1,
            fields='files(id, name, createdTime)'
        ).execute()

        files = results.get('files', [])
        return files[0] if files else None

    except Exception as e:
        logger.error(f"Failed to find backup: {e}")
        return None

def _download_from_drive(file_info):
    try:
        import base64
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        import io

        creds_json = base64.b64decode(Config.GOOGLE_DRIVE_CREDENTIALS).decode('utf-8')
        creds_dict = json.loads(creds_json)

        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )

        service = build('drive', 'v3', credentials=credentials)

        request = service.files().get_media(fileId=file_info['id'])
        file_content = request.execute()

        return json.loads(file_content.decode('utf-8'))

    except Exception as e:
        logger.error(f"Failed to download backup: {e}")
        return None

def _clean_old_backups(service):
    try:
        query = "name contains 'synapse_backup'"
        if Config.GOOGLE_DRIVE_FOLDER_ID:
            query += f" and '{Config.GOOGLE_DRIVE_FOLDER_ID}' in parents"

        results = service.files().list(
            q=query,
            orderBy='createdTime desc',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])

        for file in files[7:]:
            service.files().delete(fileId=file['id']).execute()
            logger.info(f"Deleted old backup: {file['name']}")

    except Exception as e:
        logger.warning(f"Failed to clean old backups: {e}")

def _log_backup(status, items, size_bytes, error=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO backup_log (status, items_backed_up, size_bytes, error_message)
            VALUES (?, ?, ?, ?)
        ''', (status, items, size_bytes, error))
        conn.commit()
        conn.close()
    except Exception:
        pass
