from __future__ import annotations

import httpx

from dingtalk_connector.intake import ConnectorSettings, DingTalkFile, DownloadedFile


class DingTalkDownloader:
    def __init__(self, settings: ConnectorSettings, *, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.client = httpx.Client(timeout=60, follow_redirects=True, transport=transport)
        self._access_token = ""

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        response = self.client.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": self.settings.client_id, "appSecret": self.settings.client_secret},
        )
        response.raise_for_status()
        self._access_token = response.json()["accessToken"]
        return self._access_token

    def download(self, attachment: DingTalkFile) -> DownloadedFile:
        token = self._get_access_token()
        metadata_response = self.client.post(
            "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
            headers={"x-acs-dingtalk-access-token": token},
            json={
                "downloadCode": attachment.download_code,
                "robotCode": attachment.robot_code or self.settings.robot_code,
            },
        )
        metadata_response.raise_for_status()
        download_url = metadata_response.json()["downloadUrl"]
        file_response = self.client.get(download_url)
        file_response.raise_for_status()
        return DownloadedFile(
            name=attachment.name,
            mime_type=file_response.headers.get("content-type", attachment.mime_type),
            content=file_response.content,
        )
