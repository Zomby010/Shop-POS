"""File storage in the database, for running online where files written to disk don't last."""

import mimetypes

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.http import Http404, HttpResponse
from django.utils.deconstruct import deconstructible


@deconstructible
class DatabaseStorage(Storage):
    def _model(self):
        from .models import StoredFile

        return StoredFile

    def _open(self, name, mode="rb"):
        try:
            row = self._model().objects.get(name=name)
        except self._model().DoesNotExist:
            raise FileNotFoundError(name)
        f = ContentFile(bytes(row.content), name=name)
        return f

    def _save(self, name, content):
        content.seek(0)
        data = content.read()
        self._model().objects.update_or_create(name=name, defaults={"content": data, "size": len(data)})
        return name

    def exists(self, name):
        return self._model().objects.filter(name=name).exists()

    def delete(self, name):
        self._model().objects.filter(name=name).delete()

    def size(self, name):
        row = self._model().objects.filter(name=name).values("size").first()
        if row is None:
            raise FileNotFoundError(name)
        return row["size"]

    def url(self, name):
        return f"/{settings.MEDIA_URL.lstrip('/')}{name}"


def serve_stored_file(request, path):
    from .models import StoredFile

    row = StoredFile.objects.filter(name=path).first()
    if row is None:
        raise Http404
    response = HttpResponse(bytes(row.content), content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
    response["Cache-Control"] = "public, max-age=86400"
    return response
