import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

export const AGENT_META = {
  alpha: { name: "Alpha", accent: "#22D3EE", model: "gpt-5.2", provider: "openai" },
  beta:  { name: "Beta",  accent: "#FACC15", model: "claude-sonnet-4.5", provider: "anthropic" },
  gamma: { name: "Gamma", accent: "#F43F5E", model: "gemini-3-flash",     provider: "gemini" },
};
