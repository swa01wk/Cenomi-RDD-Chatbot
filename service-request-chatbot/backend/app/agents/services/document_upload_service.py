"""File upload API integration."""

class DocumentUploadService:
    async def register_upload(self, filename: str, content_type: str) -> str:
        _ = (filename, content_type)
        return "placeholder-document-id"
