"""Tests for LinuxNotificationService."""

from unittest.mock import MagicMock, patch

import pytest

from hpc_studio.core.notifications import LinuxNotificationService


@pytest.fixture
def notification_service():
    return LinuxNotificationService()


def test_notify_success_via_subprocess(notification_service):
    sent_signals = []
    notification_service.notification_sent.connect(
        lambda title, msg, urg: sent_signals.append((title, msg, urg))
    )

    with patch("shutil.which", return_value="/usr/bin/notify-send"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        result = notification_service.notify(
            title="Prueba",
            message="Contenido de prueba",
            urgency="critical",
            icon="dialog-error",
        )

        assert result is True
        assert mock_run.called
        cmd_called = mock_run.call_args[0][0]
        assert "/usr/bin/notify-send" in cmd_called
        assert "--urgency" in cmd_called
        assert "critical" in cmd_called
        assert "Prueba" in cmd_called
        assert "Contenido de prueba" in cmd_called

        assert len(sent_signals) == 1
        assert sent_signals[0] == ("Prueba", "Contenido de prueba", "critical")


def test_notify_fallback_tray_when_subprocess_fails(notification_service):
    sent_signals = []
    notification_service.notification_sent.connect(
        lambda title, msg, urg: sent_signals.append((title, msg, urg))
    )

    mock_tray = MagicMock()
    with patch("shutil.which", return_value="/usr/bin/notify-send"), \
         patch("subprocess.run", side_effect=OSError("Command failed")), \
         patch.object(notification_service, "_get_tray_icon", return_value=mock_tray):

        result = notification_service.notify(
            title="Alerta",
            message="Mensaje importante",
            urgency="normal",
        )

        assert result is True
        assert mock_tray.showMessage.called
        assert len(sent_signals) == 1
        assert sent_signals[0] == ("Alerta", "Mensaje importante", "normal")


def test_notify_logged_when_no_display(notification_service):
    sent_signals = []
    notification_service.notification_sent.connect(
        lambda title, msg, urg: sent_signals.append((title, msg, urg))
    )

    with patch("shutil.which", return_value=None), \
         patch.object(notification_service, "_get_tray_icon", return_value=None):

        result = notification_service.notify(
            title="Headless",
            message="Ejecución sin entorno gráfico",
            urgency="low",
        )

        assert result is False
        assert len(sent_signals) == 1
        assert sent_signals[0] == ("Headless", "Ejecución sin entorno gráfico", "low")


@pytest.mark.parametrize(
    "event_type, expected_title, expected_urgency",
    [
        ("started", "Trabajo Slurm Iniciado", "normal"),
        ("completed", "Trabajo Slurm Completado", "normal"),
        ("failed", "Fallo en Trabajo Slurm", "critical"),
        ("timeout", "Trabajo Slurm Excedió Tiempo", "critical"),
    ],
)
def test_notify_job_event(notification_service, event_type, expected_title, expected_urgency):
    with patch.object(notification_service, "notify") as mock_notify:
        mock_notify.return_value = True

        notification_service.notify_job_event(
            job_id="12345",
            job_name="qe_scf_calc",
            event_type=event_type,
            details="Info adicional",
        )

        assert mock_notify.called
        kwargs = mock_notify.call_args[1]
        assert kwargs["title"] == expected_title
        assert kwargs["urgency"] == expected_urgency
        assert "12345" in kwargs["message"]
        assert "qe_scf_calc" in kwargs["message"]
        assert "Info adicional" in kwargs["message"]


@pytest.mark.parametrize(
    "event_type, expected_title, expected_urgency",
    [
        ("completed", "Convergencia Cuántica Alcanzada", "normal"),
        ("convergence_failed", "Fallo de Convergencia SCF", "critical"),
        ("crash", "Error Crítico en Ejecución", "critical"),
    ],
)
def test_notify_convergence_event(notification_service, event_type, expected_title, expected_urgency):
    with patch.object(notification_service, "notify") as mock_notify:
        mock_notify.return_value = True

        notification_service.notify_convergence_event(
            event_type=event_type,
            details="Paso 42 de cálculo",
        )

        assert mock_notify.called
        kwargs = mock_notify.call_args[1]
        assert kwargs["title"] == expected_title
        assert kwargs["urgency"] == expected_urgency
        assert "Paso 42 de cálculo" in kwargs["message"]


@pytest.mark.parametrize(
    "error_type, details, expected_title",
    [
        ("Out of Memory (OOM)", "slurmstepd: error: Exceeded job memory limit", "Fallo Crítico: Out of Memory (OOM)"),
        ("Segmentation Fault", "Program received signal SIGSEGV", "Fallo Crítico: Segmentation Fault"),
    ],
)
def test_notify_calculation_error(notification_service, error_type, details, expected_title):
    with patch.object(notification_service, "notify") as mock_notify:
        mock_notify.return_value = True

        notification_service.notify_calculation_error(
            error_type=error_type,
            details=details,
        )

        assert mock_notify.called
        kwargs = mock_notify.call_args[1]
        assert kwargs["title"] == expected_title
        assert kwargs["urgency"] == "critical"
        assert kwargs["icon"] == "dialog-error"
        assert error_type in kwargs["message"]
        assert details in kwargs["message"]

