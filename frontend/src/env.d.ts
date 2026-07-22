declare namespace NodeJS {
  interface ProcessEnv {
    EXPO_PUBLIC_API_BASE_URL?: string;
    EXPO_PUBLIC_TRANSPORT_MODE_SELECTOR_ENABLED?: string;
  }
}

declare const process: {
  env: NodeJS.ProcessEnv;
};
