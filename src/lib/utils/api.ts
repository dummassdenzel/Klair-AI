import { apiActions } from '../stores/api';

// Error handling utilities
export const handleApiError = (error: any, context: string = 'API call') => {
  console.error(`❌ ${context} failed:`, error);
  
  let userMessage = 'An unexpected error occurred';
  
  if (error.response?.data?.detail) {
    userMessage = error.response.data.detail;
  } else if (error.message) {
    userMessage = error.message;
  }
  
  apiActions.setError(userMessage);
  return userMessage;
};

// Success handling utilities
export const handleApiSuccess = (message: string) => {
  console.log(`✅ ${message}`);
  // You can add toast notifications here later
};

// Request utilities
export const createApiRequest = async <T>(
  apiCall: () => Promise<T>,
  context: string = 'API call'
): Promise<T | null> => {
  try {
    apiActions.setLoading(true);
    apiActions.clearError();
    
    const result = await apiCall();
    handleApiSuccess(`${context} completed successfully`);
    return result;
    
  } catch (err) {
    handleApiError(err, context);
    return null;
  } finally {
    apiActions.setLoading(false);
  }
};