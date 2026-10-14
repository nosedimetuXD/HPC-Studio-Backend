"""Native Linux desktop notification service for HPC Studio.

Sends alerts using notify-send via subprocess, with seamless fallback to QSystemTrayIcon
when running inside a graphical Qt desktop environment.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

from hpc_studio.core.signals import QObject, Signal

logger = logging.getLogger(__name__)


class LinuxNotificationService(QObject):
    """Handles native desktop notifications via notify-send."""

    notification_sent = Signal(str, str, str)  # (title, message, urgency)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._notify_send_path: Optional[str] = shutil.which("notify-send")
        self._tray_icon = None

    def _get_tray_icon(self) -> None:
        """Fallback when running without Qt GUI."""
        return None

    def notify(
        self,
        title: str,
        message: str,
        urgency: str = "normal",
        icon: str = "dialog-information",
    ) -> bool:
        """Attempt to dispatch a native desktop notification.

        Args:
            title: Notification title.
            message: Notification body text.
            urgency: One of 'low', 'normal', 'critical'.
            icon: Icon name or path (e.g. 'dialog-information', 'dialog-warning', 'dialog-error').

        Returns:
            bool: True if notification was sent through notify-send or QSystemTrayIcon.
        """
        valid_urgencies = {"low", "normal", "critical"}
        safe_urgency = urgency.lower() if urgency.lower() in valid_urgencies else "normal"

        # 1. Try notify-send command line
        notify_path = shutil.which("notify-send") if self._notify_send_path is None or shutil.which("notify-send") else self._notify_send_path
        if shutil.which("notify-send") is None:
            notify_path = None
        else:
            notify_path = shutil.which("notify-send")

        if notify_path:
            try:
                cmd = [
                    notify_path,
                    "--urgency", safe_urgency,
                    "--icon", icon,
                    "--app-name", "HPC Studio",
                    title,
                    message,
                ]
                subprocess.run(
                    cmd,
                    check=True,
                    timeout=5,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("Sent desktop notification via notify-send: [%s] %s", title, message)
                self.notification_sent.emit(title, message, safe_urgency)
                return True
            except Exception as exc:
                logger.warning("notify-send execution failed: %s, falling back to tray", exc)

        # 2. Fallback to tray if available
        tray = self._get_tray_icon()
        if tray is not None:
            try:
                tray_icon_type = 1
                try:
                    from PySide6.QtWidgets import QSystemTrayIcon
                    if safe_urgency == "critical":
                        tray_icon_type = QSystemTrayIcon.MessageIcon.Critical
                    elif safe_urgency == "low":
                        tray_icon_type = QSystemTrayIcon.MessageIcon.Information
                    else:
                        tray_icon_type = QSystemTrayIcon.MessageIcon.Information
                except (ImportError, AttributeError):
                    pass

                tray.showMessage(title, message, tray_icon_type, 5000)
                logger.info("Sent desktop notification via tray: [%s] %s", title, message)
                self.notification_sent.emit(title, message, safe_urgency)
                return True
            except Exception as exc:
                logger.warning("Tray showMessage failed: %s", exc)

        # 3. Log event when both mechanisms unavailable
        logger.info("Notification logged (no GUI/notify-send): [%s] %s (urgency=%s)", title, message, safe_urgency)
        self.notification_sent.emit(title, message, safe_urgency)
        return False


    def notify_job_event(
        self,
        job_id: str,
        job_name: str,
        event_type: str,
        details: str = "",
    ) -> bool:
        """Send notification tailored for Slurm job lifecycle transitions.

        Supported event types:
            - 'started': Job started running
            - 'completed': Job finished successfully
            - 'failed': Job aborted or failed
            - 'timeout': Job reached time limit
        """
        event = event_type.lower().strip()
        name_tag = f" ({job_name})" if job_name else ""

        if event == "started":
            title = "Trabajo Slurm Iniciado"
            urgency = "normal"
            icon = "dialog-information"
            msg = f"El trabajo #{job_id}{name_tag} ha comenzado su ejecución."
        elif event == "completed":
            title = "Trabajo Slurm Completado"
            urgency = "normal"
            icon = "dialog-information"
            msg = f"El trabajo #{job_id}{name_tag} ha finalizado con éxito."
        elif event == "failed":
            title = "Fallo en Trabajo Slurm"
            urgency = "critical"
            icon = "dialog-error"
            msg = f"El trabajo #{job_id}{name_tag} falló o terminó de forma anormal."
        elif event == "timeout":
            title = "Trabajo Slurm Excedió Tiempo"
            urgency = "critical"
            icon = "dialog-warning"
            msg = f"El trabajo #{job_id}{name_tag} fue cancelado por límite de tiempo (TIMEOUT)."
        else:
            title = f"Evento en Trabajo Slurm: {event_type}"
            urgency = "normal"
            icon = "dialog-information"
            msg = f"Trabajo #{job_id}{name_tag}: {details or event_type}"

        if details:
            msg += f"\nDetalles: {details}"

        return self.notify(title=title, message=msg, urgency=urgency, icon=icon)

    def notify_convergence_event(self, event_type: str, details: str) -> bool:
        """Send notification tailored for calculation convergence and execution state."""
        event = event_type.lower().strip()

        if event in ("completed", "job_done", "done"):
            title = "Convergencia Cuántica Alcanzada"
            urgency = "normal"
            icon = "dialog-information"
            msg = f"Cálculo finalizado con éxito.\n{details}" if details else "Cálculo finalizado con éxito."
        elif event in ("convergence_failed", "unconverged", "failed"):
            title = "Fallo de Convergencia SCF"
            urgency = "critical"
            icon = "dialog-warning"
            msg = f"El cálculo no logró converger en el número de iteraciones asignado.\n{details}" if details else "Fallo de convergencia SCF."
        elif event in ("error", "crash", "system_error"):
            title = "Error Crítico en Ejecución"
            urgency = "critical"
            icon = "dialog-error"
            msg = f"Se detectó un fallo crítico en el motor de cálculo.\n{details}" if details else "Error en la rutina de cálculo."
        else:
            title = "Notificación de Cálculo Cuántico"
            urgency = "normal"
            icon = "dialog-information"
            msg = details or event_type

        return self.notify(title=title, message=msg, urgency=urgency, icon=icon)

    def notify_calculation_error(self, error_type: str, details: str = "") -> bool:
        """Send desktop notification tailored for calculation crashes and system faults (OOM, Segfault, etc.)."""
        title = f"Fallo Crítico: {error_type}" if error_type else "Error Crítico en Ejecución"
        msg = f"Se detectó un fallo crítico en el motor de cálculo: {error_type}."
        if details:
            msg += f"\nDetalles: {details}"
        return self.notify(title=title, message=msg, urgency="critical", icon="dialog-error")

