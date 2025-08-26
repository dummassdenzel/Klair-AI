// Environment configuration
export const config = {
    // API Configuration
    api: {
      baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api',
      timeout: 30000,
    },
  
    // Feature Flags
    features: {
      realTimeUpdates: true,
      fileUpload: false, // For future implementation
      advancedSearch: true,
    },
  
    // UI Configuration
    ui: {
      maxMessageLength: 1000,
      autoScrollChat: true,
      showFilePreviews: true,
    },
  };
  
  // Development helpers
  export const isDevelopment = import.meta.env.DEV;
  export const isProduction = import.meta.env.PROD;