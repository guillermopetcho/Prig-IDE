use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalZone {
    pub name: String,
    pub temp_c: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryStats {
    pub total_mb: u64,
    pub available_mb: u64,
    pub used_mb: u64,
    pub used_percent: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CpuStats {
    pub load_1m: f64,
    pub load_5m: f64,
    pub load_15m: f64,
    pub core_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareTelemetry {
    pub cpu_temp_c: Option<f64>,
    pub thermal_zones: Vec<ThermalZone>,
    pub memory: Option<MemoryStats>,
    pub cpu: Option<CpuStats>,
}

pub struct HardwareMonitor;

impl HardwareMonitor {
    pub fn read_telemetry() -> HardwareTelemetry {
        let zones = Self::read_thermal_zones();
        let cpu_temp_c = Self::find_primary_cpu_temp(&zones);
        let memory = Self::read_memory();
        let cpu = Self::read_cpu();

        HardwareTelemetry {
            cpu_temp_c,
            thermal_zones: zones,
            memory,
            cpu,
        }
    }

    pub fn read_thermal_zones() -> Vec<ThermalZone> {
        let mut zones = Vec::new();
        let thermal_dir = Path::new("/sys/class/thermal");
        if !thermal_dir.is_dir() {
            return zones;
        }

        if let Ok(entries) = fs::read_dir(thermal_dir) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.starts_with("thermal_zone") {
                    let type_file = entry.path().join("type");
                    let temp_file = entry.path().join("temp");

                    let zone_name = fs::read_to_string(&type_file)
                        .map(|s| s.trim().to_string())
                        .unwrap_or(name);

                    if let Ok(temp_str) = fs::read_to_string(&temp_file) {
                        if let Ok(milli_c) = temp_str.trim().parse::<f64>() {
                            let temp_c = (milli_c / 1000.0 * 10.0).round() / 10.0;
                            zones.push(ThermalZone {
                                name: zone_name,
                                temp_c,
                            });
                        }
                    }
                }
            }
        }

        zones
    }

    fn find_primary_cpu_temp(zones: &[ThermalZone]) -> Option<f64> {
        // Buscar x86_pkg_temp o TCPU o cpu
        for z in zones {
            let lower = z.name.to_lowercase();
            if lower.contains("pkg_temp") || lower.contains("x86_pkg") {
                return Some(z.temp_c);
            }
        }
        for z in zones {
            let lower = z.name.to_lowercase();
            if lower.contains("tcpu") || lower.contains("cpu") {
                return Some(z.temp_c);
            }
        }
        zones.first().map(|z| z.temp_c)
    }

    pub fn read_memory() -> Option<MemoryStats> {
        let meminfo = fs::read_to_string("/proc/meminfo").ok()?;
        let mut total_kb = 0u64;
        let mut avail_kb = 0u64;

        for line in meminfo.lines() {
            if line.starts_with("MemTotal:") {
                total_kb = parse_kb_line(line);
            } else if line.starts_with("MemAvailable:") {
                avail_kb = parse_kb_line(line);
            }
        }

        if total_kb == 0 {
            return None;
        }

        let total_mb = total_kb / 1024;
        let available_mb = avail_kb / 1024;
        let used_mb = total_mb.saturating_sub(available_mb);
        let used_percent = if total_mb > 0 {
            ((used_mb as f64 / total_mb as f64) * 1000.0).round() / 10.0
        } else {
            0.0
        };

        Some(MemoryStats {
            total_mb,
            available_mb,
            used_mb,
            used_percent,
        })
    }

    pub fn read_cpu() -> Option<CpuStats> {
        let loadavg = fs::read_to_string("/proc/loadavg").ok()?;
        let parts: Vec<&str> = loadavg.split_whitespace().collect();
        if parts.len() < 3 {
            return None;
        }

        let load_1m = parts[0].parse::<f64>().unwrap_or(0.0);
        let load_5m = parts[1].parse::<f64>().unwrap_or(0.0);
        let load_15m = parts[2].parse::<f64>().unwrap_or(0.0);

        let core_count = fs::read_to_string("/proc/cpuinfo")
            .map(|s| s.lines().filter(|l| l.starts_with("processor\t:")).count())
            .unwrap_or(1)
            .max(1);

        Some(CpuStats {
            load_1m,
            load_5m,
            load_15m,
            core_count,
        })
    }
}

fn parse_kb_line(line: &str) -> u64 {
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() >= 2 {
        parts[1].parse::<u64>().unwrap_or(0)
    } else {
        0
    }
}

