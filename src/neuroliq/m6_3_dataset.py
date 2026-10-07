"""Изолированный сетевой адаптер только для исследовательского запуска M6.3."""

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import shutil

DATASET = "deepvk/cultura_ru_edu_llama3_annotations"
REVISION = "1082c2c8ac044d5fe1a9a27cb942e98ba7fa3110"
SPLIT = "validation"
SHARD = "data/validation-00000-of-00001.parquet"


def text_documents(source: Iterable[Mapping]) -> Iterator[str]:
    """Взять только text в исходном порядке; один row — один документ."""
    for row in source:
        text = row["text"]
        if not isinstance(text, str):
            raise ValueError("Поле text должно быть строкой")
        yield text


def validation_documents(source: Iterable[Mapping] | None = None) -> Iterator[str]:
    """Подставной source не использует сеть и не требует pyarrow."""
    if source is not None:
        yield from text_documents(source)
        return
    import pyarrow.parquet as pq

    url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{SHARD}"
    with TemporaryDirectory(prefix="neuroliq-m6-3-") as directory:
        path = Path(directory) / "validation.parquet"
        with urlopen(url, timeout=60) as response, path.open("wb") as output:
            shutil.copyfileobj(response, output)
        parquet = pq.ParquetFile(path)
        try:
            for batch in parquet.iter_batches(batch_size=64, columns=["text"]):
                yield from text_documents(batch.to_pylist())
        finally:
            parquet.close()
