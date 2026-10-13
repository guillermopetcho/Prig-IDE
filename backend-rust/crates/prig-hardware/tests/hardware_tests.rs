use prig_hardware::HardwareMonitor;

#[test]
fn test_read_memory_proc() {
    let mem = HardwareMonitor::read_memory();
    assert!(mem.is_some());
    let m = mem.unwrap();
    assert!(m.total_mb > 0);
    assert!(m.available_mb > 0);
    assert!(m.used_percent >= 0.0 && m.used_percent <= 100.0);
}

#[test]
fn test_read_cpu_proc() {
    let cpu = HardwareMonitor::read_cpu();
    assert!(cpu.is_some());
    let c = cpu.unwrap();
    assert!(c.core_count >= 1);
}

#[test]
fn test_read_full_telemetry() {
    let telemetry = HardwareMonitor::read_telemetry();
    assert!(telemetry.memory.is_some());
    assert!(telemetry.cpu.is_some());
    // Las zonas térmicas pueden estar presentes en hardware real Linux
    if !telemetry.thermal_zones.is_empty() {
        assert!(telemetry.cpu_temp_c.is_some());
    }
}

