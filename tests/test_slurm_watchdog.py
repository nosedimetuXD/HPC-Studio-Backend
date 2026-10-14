"""Tests for ConvergenceWatchdog."""

import pytest

from hpc_studio.slurm.watchdog import ConvergenceWatchdog


@pytest.fixture
def watchdog():
    return ConvergenceWatchdog()


def test_initial_state(watchdog):
    assert watchdog.current_iteration == 0
    assert watchdog.current_energy is None
    assert watchdog.current_accuracy is None
    assert watchdog.status_text == "Esperando cálculo..."
    assert not watchdog.is_done
    assert not watchdog.has_error


def test_parse_scf_iteration_energy_accuracy(watchdog):
    scf_steps = []
    watchdog.scf_step_detected.connect(lambda it, en, acc: scf_steps.append((it, en, acc)))

    # Line 1: iteration
    watchdog.process_line("     iteration #   4")
    assert watchdog.current_iteration == 4
    assert watchdog.status_text == "Iteración 4"

    # Line 2: energy
    watchdog.process_line("!    total energy              =     -123.45678901 Ry")
    assert watchdog.current_energy == pytest.approx(-123.45678901)

    # Line 3: accuracy (triggers scf_step_detected)
    watchdog.process_line("     estimated scf accuracy    <          0.00012345 Ry")
    assert watchdog.current_accuracy == pytest.approx(0.00012345)

    assert len(scf_steps) == 1
    assert scf_steps[0] == (4, pytest.approx(-123.45678901), pytest.approx(0.00012345))


def test_scientific_notation_accuracy(watchdog):
    scf_steps = []
    watchdog.scf_step_detected.connect(lambda it, en, acc: scf_steps.append((it, en, acc)))

    watchdog.process_line("iteration # 10")
    watchdog.process_line("total energy = -54.12000000 Ry")
    watchdog.process_line("estimated scf accuracy < 1.23E-07 Ry")

    assert watchdog.current_iteration == 10
    assert watchdog.current_energy == pytest.approx(-54.12)
    assert watchdog.current_accuracy == pytest.approx(1.23e-7)
    assert len(scf_steps) == 1
    assert scf_steps[0][2] == pytest.approx(1.23e-7)


def test_job_completed_detection(watchdog):
    completed_events = []
    watchdog.job_completed.connect(completed_events.append)

    watchdog.process_line("     JOB DONE.")
    assert watchdog.is_done
    assert "finalizado" in watchdog.status_text.lower()
    assert completed_events == ["JOB DONE."]


def test_convergence_failed_detection(watchdog):
    failed_events = []
    watchdog.convergence_failed.connect(failed_events.append)

    fail_line = "convergence NOT achieved after 100 iterations: stopping"
    watchdog.process_line(fail_line)
    assert watchdog.has_error
    assert "convergencia" in watchdog.status_text.lower()
    assert len(failed_events) == 1
    assert fail_line in failed_events[0]


@pytest.mark.parametrize(
    "error_line, expected_type",
    [
        ("slurmstepd: error: Detected 1 oom-kill event(s)", "OOM"),
        ("slurmstepd: error: Job exceeded memory limit: OUT OF MEMORY", "OOM"),
        ("slurmstepd: error: *** JOB CANCELLED AT 2026-10-12 DUE TO TIME LIMIT ***", "TIMEOUT"),
        ("forrtl: severe (174): SIGSEGV, segmentation fault occurred", "SIGSEGV"),
        ("Program received signal SIGSEGV: Segmentation fault.", "SIGSEGV"),
        ("%ERROR: Error in routine cdiaghg (1): S matrix not positive definite", "ROUTINE_ERROR"),
    ],
)
def test_system_error_detection(watchdog, error_line, expected_type):
    errors = []
    watchdog.system_error_detected.connect(lambda err_type, line: errors.append((err_type, line)))

    watchdog.process_line(error_line)
    assert watchdog.has_error
    assert len(errors) == 1
    assert errors[0][0] == expected_type
    assert errors[0][1] == error_line


def test_reset(watchdog):
    watchdog.process_line("iteration # 5")
    watchdog.process_line("total energy = -10.0 Ry")
    watchdog.process_line("JOB DONE.")

    assert watchdog.is_done
    assert watchdog.current_iteration == 5

    watchdog.reset()
    assert watchdog.current_iteration == 0
    assert watchdog.current_energy is None
    assert watchdog.current_accuracy is None
    assert not watchdog.is_done
    assert not watchdog.has_error
    assert watchdog.status_text == "Esperando cálculo..."
