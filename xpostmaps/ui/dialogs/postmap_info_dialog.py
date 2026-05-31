"""Editable postmap information popup."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from xpostmaps.core.models import PostmapInfo
from xpostmaps.ui.dialogs.base_dialog import SingleInstanceDialog


class PostmapInfoDialog:
    KEY = "postmap_info"

    @classmethod
    def open(cls, parent, info: PostmapInfo, on_changed) -> None:
        def build(dialog: SingleInstanceDialog) -> None:
            layout = dialog.content_layout
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            title = QLabel("Postmap Information")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            fields: dict[str, QLineEdit] = {}
            form = QFormLayout()
            form.setSpacing(10)

            field_defs = [
                ("client", "Client Name"),
                ("area", "Area"),
                ("project", "Project Name"),
                ("title", "Title"),
                ("job_number", "Job Number"),
                ("client_ref", "Client Project Reference"),
                ("crs_name", "Coordinate Reference System"),
                ("projection", "Projection"),
                ("epsg_code", "EPSG Code"),
                ("date", "Date"),
            ]

            for key, label in field_defs:
                edit = QLineEdit(getattr(info, key, "") or "")
                fields[key] = edit
                form.addRow(label, edit)

            form_host = QVBoxLayout()
            w = dialog
            from PySide6.QtWidgets import QWidget

            form_widget = QWidget()
            form_widget.setLayout(form)
            layout.addWidget(form_widget)

            def apply() -> None:
                updated = PostmapInfo(
                    company_name=info.company_name,
                    title=fields["title"].text().strip(),
                    job_number=fields["job_number"].text().strip(),
                    client=fields["client"].text().strip(),
                    area=fields["area"].text().strip(),
                    project=fields["project"].text().strip(),
                    client_ref=fields["client_ref"].text().strip(),
                    file_name=info.file_name,
                    user_name=info.user_name,
                    date=fields["date"].text().strip(),
                    crs_name=fields["crs_name"].text().strip(),
                    projection=fields["projection"].text().strip(),
                    epsg_code=fields["epsg_code"].text().strip(),
                    geographic_datum=info.geographic_datum,
                    spheroid=info.spheroid,
                    semi_major_axis=info.semi_major_axis,
                    inverse_flattening=info.inverse_flattening,
                    eccentricity=info.eccentricity,
                    extra=info.extra,
                )
                on_changed(updated)

            apply_btn = QPushButton("Apply")
            apply_btn.setObjectName("primaryBtn")
            apply_btn.clicked.connect(apply)
            layout.addWidget(apply_btn)

            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.close)
            layout.addWidget(close_btn)

        SingleInstanceDialog.show_dialog(
            cls.KEY, "Postmap Information", build, parent, width=480
        )
