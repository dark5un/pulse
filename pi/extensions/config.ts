export interface Config {
  autoAnalyze: boolean;
}

const defaultConfig: Config = {
  autoAnalyze: false,
};

let config: Config = defaultConfig;

export function loadConfig(): Config {
  const envAutoAnalyze = process.env.PULSE_AUTO_ANALYZE;
  if (envAutoAnalyze !== undefined) {
    config.autoAnalyze = envAutoAnalyze === "true" || envAutoAnalyze === "1";
  }
  return config;
}

export function saveConfig(config: Config): void {
  process.env.PULSE_AUTO_ANALYZE = config.autoAnalyze ? "1" : "0";
}

export function resetConfig(): void {
  delete process.env.PULSE_AUTO_ANALYZE;
  config = defaultConfig;
}
