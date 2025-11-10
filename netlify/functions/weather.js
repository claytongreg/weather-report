// Netlify Serverless Function: weather.js
// This securely fetches weather data without exposing your API key

exports.handler = async function(event, context) {
  // Enable CORS for your frontend
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Content-Type': 'application/json',
    'Cache-Control': 'public, max-age=300' // Cache for 5 minutes
  };
  
  // Handle preflight requests
  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 200,
      headers,
      body: ''
    };
  }
  
  // Only allow GET requests
  if (event.httpMethod !== 'GET') {
    return {
      statusCode: 405,
      headers,
      body: JSON.stringify({ error: 'Method not allowed' })
    };
  }
  
  try {
    // Get API key from environment variable (set in Netlify dashboard)
    const API_KEY = process.env.OPENWEATHER_API_KEY;
    
    if (!API_KEY) {
      throw new Error('API key not configured');
    }
    
    // Birchdale coordinates
    const LAT = 50.038417;
    const LON = -116.892033;
    
    // Build OpenWeather API URL
    const url = `https://api.openweathermap.org/data/3.0/onecall?lat=${LAT}&lon=${LON}&appid=${API_KEY}&units=metric&exclude=minutely,alerts`;
    
    console.log('Fetching weather data...');
    
    // Fetch weather data
    const response = await fetch(url);
    
    if (!response.ok) {
      throw new Error(`OpenWeather API returned ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    console.log('Weather data fetched successfully');
    
    // Return the weather data
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify(data)
    };
    
  } catch (error) {
    console.error('Error fetching weather:', error);
    
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ 
        error: 'Failed to fetch weather data',
        message: error.message
      })
    };
  }
};
