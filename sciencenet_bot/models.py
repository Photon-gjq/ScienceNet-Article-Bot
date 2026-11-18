from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    author: str
    url: str
    label: str

    def message(self) -> str:
        return f"{self.title}\n作者: {self.author}\n分類: {self.label}\n鏈結: {self.url}"
