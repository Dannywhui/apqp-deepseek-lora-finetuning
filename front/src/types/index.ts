// 消息类型
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  sources?: SourceSummary[];
}

export interface SourceSummary {
  source: string;
  label: string;
  pages?: number[];
  chunks?: number[];
  score?: number;
}

// 对话历史
export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

// API 请求格式 (OpenAI 兼容)
export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  session_id?: string;
  temperature?: number;
  max_new_tokens?: number;
  top_p?: number;
  stream?: boolean;
}

export interface ChatResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: {
    index: number;
    message: {
      role: string;
      content: string;
    };
    sources?: SourceSummary[];
    finish_reason: string;
  }[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ValidationSummary {
  pfd_process_count: number;
  pfd_characteristic_count: number;
  fmea_failure_count: number;
  fmea_process_count: number;
  control_plan_control_count: number;
}

export interface ValidationPassedItem {
  pfd_item?: string;
  fmea_item?: string;
  fmea_match?: string;
  control_plan_match?: string;
}

export interface ValidationMissingItem {
  pfd_item?: string;
  fmea_item?: string;
  reason: string;
}

export interface ValidationCheck {
  category: string;
  description: string;
  passed: ValidationPassedItem[];
  missing: ValidationMissingItem[];
}

export interface ValidationResult {
  summary: ValidationSummary;
  checks: ValidationCheck[];
}

export interface ValidateDocumentsResponse {
  code: number;
  message: string;
  data: ValidationResult;
  report: string;
  warnings?: string[];
}
