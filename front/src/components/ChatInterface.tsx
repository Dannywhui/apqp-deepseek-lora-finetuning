import { useState, useRef, useEffect } from "react";
import {
  Send,
  Loader2,
  Moon,
  Sun,
  User,
  Menu,
  Trash2,
  Plus,
  FileSearch,
  Paperclip,
  ClipboardCheck,
  MessageSquareText,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Workflow,
  ChevronRight,
  X,
  ArrowLeft,
} from "lucide-react";
import { Message, Conversation, SourceSummary, ValidateDocumentsResponse } from "../types";
import {
  sendChatMessage,
  generateId,
  generateTitle,
  saveConversations,
  loadConversations,
} from "../utils";
import { useTheme } from "../hooks/useTheme";
import MarkdownRenderer from "./MarkdownRenderer";

const MODEL_NAME = "DeepSeek Local Model";

type ValidationMode = 'normal' | 'validate';

export default function ChatInterface() {
  const { theme, toggleTheme } = useTheme();
  const [conversations, setConversations] = useState<Conversation[]>(() =>
    loadConversations(),
  );
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(null);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileUploadLoading, setFileUploadLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [validationMode, setValidationMode] = useState<ValidationMode>('normal');
  const [validationFiles, setValidationFiles] = useState<{
    pfd: File | null;
    fmea: File | null;
    controlPlan: File | null;
  }>({ pfd: null, fmea: null, controlPlan: null });
  const [validationLoading, setValidationLoading] = useState(false);
  const [validationResult, setValidationResult] = useState<ValidateDocumentsResponse | null>(null);
  const [highlightedKeys, setHighlightedKeys] = useState<Set<string>>(new Set());
  const pfdInputRef = useRef<HTMLInputElement>(null);
  const fmeaInputRef = useRef<HTMLInputElement>(null);
  const cpInputRef = useRef<HTMLInputElement>(null);
  const validationLockRef = useRef(false);

  const currentConversation = conversations.find(
    (c) => c.id === currentConversationId,
  );
  const messages = currentConversation?.messages || [];

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 校验结果出来后，随机标红约10条缺失项
  useEffect(() => {
    if (!validationResult) {
      setHighlightedKeys(new Set());
      return;
    }
    const allKeys: string[] = [];
    validationResult.data.checks.forEach((check, ci) => {
      check.missing.forEach((_, mi) => {
        allKeys.push(`${ci}-m-${mi}`);
      });
    });
    const target = Math.min(10, allKeys.length);
    const shuffled = allKeys.sort(() => Math.random() - 0.5);
    setHighlightedKeys(new Set(shuffled.slice(0, target)));
  }, [validationResult]);

  // 保存对话
  useEffect(() => {
    saveConversations(conversations);
  }, [conversations]);

  // 创建新对话
  const createNewConversation = () => {
    const newConversation: Conversation = {
      id: generateId(),
      title: "新对话",
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setConversations((prev) => [newConversation, ...prev]);
    setCurrentConversationId(newConversation.id);
    setInput("");
    setSelectedFile(null);
    setValidationMode('normal');
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  };

  // 选择对话
  const selectConversation = (id: string) => {
    setCurrentConversationId(id);
    setSelectedFile(null);
    setValidationMode('normal');
    if (window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  };

  // 删除对话
  const deleteConversation = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (currentConversationId === id) {
      setCurrentConversationId(null);
    }
  };

  // 发送消息
  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: input.trim(),
      timestamp: Date.now(),
    };

    // 确保当前有对话
    let convId = currentConversationId;
    if (!convId) {
      const newConversation: Conversation = {
        id: generateId(),
        title: "新对话",
        messages: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      setConversations((prev) => [newConversation, ...prev]);
      convId = newConversation.id;
      setCurrentConversationId(convId);
    }

    // 添加用户消息
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === convId) {
          return {
            ...c,
            messages: [...c.messages, userMessage],
            title:
              c.messages.length === 0
                ? generateTitle([...c.messages, userMessage])
                : c.title,
            updatedAt: Date.now(),
          };
        }
        return c;
      }),
    );

    setInput("");
    setIsLoading(true);

    try {
      const allMessages =
        conversations.find((c) => c.id === convId)?.messages || [];
      const apiMessages = [...allMessages, userMessage].map((m) => ({
        role: m.role,
        content: m.content,
      }));

      const response = await sendChatMessage(apiMessages, convId);

      const assistantMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: response.content,
        timestamp: Date.now(),
        sources: response.sources,
      };

      setConversations((prev) =>
        prev.map((c) => {
          if (c.id === convId) {
            return {
              ...c,
              messages: [...c.messages, assistantMessage],
              updatedAt: Date.now(),
            };
          }
          return c;
        }),
      );
    } catch (error) {
      const errorMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: `抱歉，发生了错误：${error instanceof Error ? error.message : "未知错误"}`,
        timestamp: Date.now(),
      };

      setConversations((prev) =>
        prev.map((c) => {
          if (c.id === convId) {
            return {
              ...c,
              messages: [...c.messages, errorMessage],
              updatedAt: Date.now(),
            };
          }
          return c;
        }),
      );
    } finally {
      setIsLoading(false);
    }
  };

  // 自动调整输入框高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height =
        Math.min(textareaRef.current.scrollHeight, 200) + "px";
    }
  }, [input]);

  // 选择本地文件
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const targetFile = e.target.files?.[0];
    if (targetFile) {
      setSelectedFile(targetFile);
    }
  };

  const removeSelectedFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // 上传文件并请求AI解析
  const handleUploadFileAndChat = async () => {
    // 基础校验
    if (!selectedFile || fileUploadLoading) return;
    setFileUploadLoading(true);

    const userPrompt = input.trim() || "请分析这个文件的内容";
    // 1. 获取/创建对话ID（复用原有新建对话逻辑）
    let convId = currentConversationId;
    if (!convId) {
      const newConversation = {
        id: generateId(),
        title: "新对话",
        messages: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      setConversations((prev) => [newConversation, ...prev]);
      convId = newConversation.id;
      setCurrentConversationId(convId);
    }

    // 2. 组装用户消息：标记上传文件 + 用户提问
    const userContent = `上传文件【${selectedFile.name}】，我的问题：${userPrompt}`;
    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: userContent,
      timestamp: Date.now(),
    };

    // 把用户消息写入对话列表
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === convId) {
          return {
            ...c,
            messages: [...c.messages, userMessage],
            title:
              c.messages.length === 0
                ? generateTitle([...c.messages, userMessage])
                : c.title,
            updatedAt: Date.now(),
          };
        }
        return c;
      }),
    );

    // 清空输入框
    setInput("");

    try {
      // 3. 调用 /chat/start_file_session 初始化文件会话
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append(
        "system_prompt",
        "你是APQP项目质量管理助手，请仅基于用户上传的文件内容回答。\n"
        + "【输出格式】【主题】… 【结论】… 【要点】… 【风险】… 【建议】…\n"
        + "【内容质量】先结论后细节；引用文件中的具体事实/指标；建议可执行；关键词用 **加粗**；不要编造文件中没有的内容。",
      );
      formData.append("session_id", convId);

      const initRes = await fetch("/chat/start_file_session", {
        method: "POST",
        body: formData,
      });
      if (!initRes.ok) {
        throw new Error(`文件会话初始化失败: ${initRes.status}`);
      }
      const initData = await initRes.json();

      // 4. 拼接 messages：使用后端返回的 system（含文件内容）+ 用户问题
      const initMessages = initData.messages as { role: string; content: string }[];
      const apiMessages = [
        ...initMessages,
        { role: "user" as const, content: userPrompt },
      ];

      // 5. 调 /chat/completions 获取 AI 回复
      const response = await sendChatMessage(apiMessages, convId);

      const assistantMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: response.content,
        timestamp: Date.now(),
        sources: response.sources,
      };

      // AI消息存入对话
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id === convId) {
            return {
              ...c,
              messages: [...c.messages, assistantMessage],
              updatedAt: Date.now(),
            };
          }
          return c;
        }),
      );
    } catch (err) {
      // 网络异常兜底消息
      const errMsg: Message = {
        id: generateId(),
        role: "assistant",
        content: `文件解析失败：${err instanceof Error ? err.message : "未知错误"}`,
        timestamp: Date.now(),
      };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId ? { ...c, messages: [...c.messages, errMsg] } : c,
        ),
      );
    } finally {
      setFileUploadLoading(false);
      setSelectedFile(null); // 上传完成清空文件
    }
  };

  // 评分+摘要：单独调 /api/v1/question_with_file
  const handleScoreFile = async () => {
    if (!selectedFile || fileUploadLoading) return;
    setFileUploadLoading(true);

    let convId = currentConversationId;
    if (!convId) {
      const newConversation = {
        id: generateId(),
        title: "新对话",
        messages: [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
      };
      setConversations((prev) => [newConversation, ...prev]);
      convId = newConversation.id;
      setCurrentConversationId(convId);
    }

    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: `对文件【${selectedFile.name}】进行评分与摘要`,
      timestamp: Date.now(),
    };

    setConversations((prev) =>
      prev.map((c) => {
        if (c.id === convId) {
          return {
            ...c,
            messages: [...c.messages, userMessage],
            title:
              c.messages.length === 0
                ? generateTitle([...c.messages, userMessage])
                : c.title,
            updatedAt: Date.now(),
          };
        }
        return c;
      }),
    );

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      formData.append("question", JSON.stringify({
        needSummary100: true,
        needSummary200: true,
        needScore: true,
      }));

      const res = await fetch("/api/v1/question_with_file", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();

      let replyContent = "文件解析失败";
      if (data.code === 0 && data.data?.answer) {
        const answer = data.data.answer;
        const parts = [];
        if (answer.summary100) parts.push(`**100字摘要：**\n${answer.summary100}`);
        if (answer.summary200) parts.push(`**200字摘要：**\n${answer.summary200}`);
        if (answer.score) parts.push(`**评分：**\n${answer.score}`);
        replyContent = parts.length > 0 ? parts.join("\n\n") : "解析完成，但无内容";
      } else {
        replyContent = `文件评分失败：${data.message || "未知错误"}`;
      }

      const aiMessage: Message = {
        id: generateId(),
        role: "assistant",
        content: replyContent,
        timestamp: Date.now(),
      };

      setConversations((prev) =>
        prev.map((c) => {
          if (c.id === convId) {
            return {
              ...c,
              messages: [...c.messages, aiMessage],
              updatedAt: Date.now(),
            };
          }
          return c;
        }),
      );
    } catch (err) {
      const errMsg: Message = {
        id: generateId(),
        role: "assistant",
        content: `评分请求失败：${err instanceof Error ? err.message : "未知错误"}`,
        timestamp: Date.now(),
      };
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId ? { ...c, messages: [...c.messages, errMsg] } : c,
        ),
      );
    } finally {
      setFileUploadLoading(false);
      setSelectedFile(null);
    }
  };

  const handleSubmit = () => {
    if (selectedFile && !fileUploadLoading) {
      handleUploadFileAndChat();
    } else if (input.trim() || !isLoading) {
      handleSend();
    }
  };

  // 处理键盘事件
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      e.stopPropagation();
      if (selectedFile) {
        handleUploadFileAndChat();
      } else if (input.trim()) {
        handleSend();
      }
    }
  };

  const handleValidationFileSelect = (type: 'pfd' | 'fmea' | 'controlPlan') => (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setValidationFiles(prev => ({ ...prev, [type]: file }));
    }
  };

  const removeValidationFile = (type: 'pfd' | 'fmea' | 'controlPlan') => () => {
    setValidationFiles(prev => ({ ...prev, [type]: null }));
    if (type === 'pfd' && pfdInputRef.current) pfdInputRef.current.value = '';
    if (type === 'fmea' && fmeaInputRef.current) fmeaInputRef.current.value = '';
    if (type === 'controlPlan' && cpInputRef.current) cpInputRef.current.value = '';
  };

  const handleValidateDocuments = async () => {
    if (!validationFiles.pfd || !validationFiles.fmea || validationLoading || validationLockRef.current) return;
    validationLockRef.current = true;
    setValidationLoading(true);
    setValidationResult(null);

    try {
      const formData = new FormData();
      formData.append('pfd_file', validationFiles.pfd);
      formData.append('fmea_file', validationFiles.fmea);
      if (validationFiles.controlPlan) {
        formData.append('control_plan_file', validationFiles.controlPlan);
      }

      const res = await fetch('/api/v1/validate_documents', {
        method: 'POST',
        body: formData,
      });

      const data: ValidateDocumentsResponse = await res.json();
      if (data.code === 0) {
        setValidationResult(data);
      } else {
        alert(`校验失败：${data.message}`);
      }
    } catch (err) {
      alert(`校验请求失败：${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setValidationLoading(false);
      validationLockRef.current = false;
    }
  };

  const clearValidation = () => {
    setValidationFiles({ pfd: null, fmea: null, controlPlan: null });
    setValidationResult(null);
    if (pfdInputRef.current) pfdInputRef.current.value = '';
    if (fmeaInputRef.current) fmeaInputRef.current.value = '';
    if (cpInputRef.current) cpInputRef.current.value = '';
  };

  const allRequiredFilesSelected = validationFiles.pfd && validationFiles.fmea;

  return (
    <div className="flex h-screen bg-background">
      {/* 侧边栏遮罩 (移动端) */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* 侧边栏 */}
      <aside
        className={`
        fixed md:static inset-y-0 left-0 z-50
        w-72 bg-card border-r border-border
        flex flex-col
        transform transition-transform duration-300 ease-in-out
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}
      `}
      >
        {/* 侧边栏头部 */}
        <div className="p-4 border-b border-border space-y-2">
          <button
            onClick={createNewConversation}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 
                     bg-primary text-primary-foreground rounded-lg
                     hover:bg-primary/90 transition-colors font-medium"
          >
            <Plus size={18} />
            <span>新对话</span>
          </button>
          <button
            onClick={() => setValidationMode(validationMode === 'normal' ? 'validate' : 'normal')}
            className={`w-full flex items-center justify-center gap-2 px-4 py-3 
                     rounded-lg transition-colors font-medium
                     ${validationMode === 'validate' 
                       ? 'bg-secondary text-secondary-foreground ring-2 ring-primary' 
                       : 'bg-muted hover:bg-muted/80'}`}
          >
            <Workflow size={18} />
            <span>跨文档校验</span>
          </button>
        </div>

        {/* 对话列表 */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-2">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => selectConversation(conv.id)}
              className={`
                group flex items-center gap-2 px-3 py-3 rounded-lg cursor-pointer
                transition-colors mb-1
                ${
                  conv.id === currentConversationId
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50 text-muted-foreground hover:text-foreground"
                }
              `}
            >
              <div className="flex-1 truncate text-sm font-medium">
                {conv.title}
              </div>
              <button
                onClick={(e) => deleteConversation(e, conv.id)}
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500 
                         transition-opacity"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>

        {/* 侧边栏底部 */}
        <div className="p-4 border-t border-border space-y-2">
          <button
            onClick={toggleTheme}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg
                     hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            <span className="text-sm">
              {theme === "dark" ? "浅色模式" : "深色模式"}
            </span>
          </button>
          <div className="flex items-center gap-3 px-3 py-2">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
              <User size={16} className="text-primary-foreground" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-medium">用户</div>
              <div className="text-xs text-muted-foreground">本地部署</div>
            </div>
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* 顶部栏 */}
        <header className="flex items-center gap-4 p-4 border-b border-border bg-card">
          <button
            onClick={() => setSidebarOpen(true)}
            className="md:hidden p-2 hover:bg-accent rounded-lg transition-colors"
          >
            <Menu size={20} />
          </button>
          <div className="flex-1">
            <h1 className="font-semibold text-lg">{MODEL_NAME}</h1>
          </div>
          <button
            onClick={toggleTheme}
            className="p-2 hover:bg-accent rounded-lg transition-colors hidden md:block"
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </header>

        {/* 消息区域 */}
        <div className="flex-1 overflow-y-auto scrollbar-thin p-4 space-y-6">
          {validationMode === 'validate' ? (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-4xl mx-auto">
                <div className="mb-6 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center">
                      <Workflow size={24} className="text-primary-foreground" />
                    </div>
                    <div>
                      <h2 className="text-xl font-bold">跨文档链路校验</h2>
                      <p className="text-sm text-muted-foreground">流程图-FMEA-控制计划 三位一体校验</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => { setValidationMode('normal'); clearValidation(); }}
                      className="flex items-center gap-1 px-3 py-2 text-sm hover:bg-accent rounded-lg transition-colors"
                      title="返回对话"
                    >
                      <ArrowLeft size={16} />
                      <span>返回对话</span>
                    </button>
                    <button
                      onClick={clearValidation}
                      className="p-2 hover:bg-accent rounded-lg transition-colors"
                      title="清空已选文件"
                    >
                      <X size={20} />
                    </button>
                  </div>
                </div>

                <div className="bg-card rounded-xl border border-border p-6 mb-6">
                  <h3 className="font-semibold mb-4 flex items-center gap-2">
                    <span className="w-6 h-6 rounded-full bg-primary text-primary-foreground text-xs flex items-center justify-center">1</span>
                    上传文档
                  </h3>
                  <div className="space-y-4">
                    <div className="flex items-center gap-4">
                      <div className={`flex-1 p-4 border-2 border-dashed rounded-lg transition-colors ${
                        validationFiles.pfd ? 'border-primary bg-primary/5' : 'border-input hover:border-primary/50'
                      }`}>
                        <label className="flex flex-col items-center gap-2 cursor-pointer w-full">
                          <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                            validationFiles.pfd ? 'bg-primary/20' : 'bg-muted'
                          }`}>
                            <span className="text-2xl">📋</span>
                          </div>
                          <span className="text-sm font-medium">PFD流程图</span>
                          <span className="text-xs text-muted-foreground">必填</span>
                          {validationFiles.pfd && (
                            <span className="text-xs text-primary truncate max-w-xs">{validationFiles.pfd.name}</span>
                          )}
                          <input
                            ref={pfdInputRef}
                            type="file"
                            onChange={handleValidationFileSelect('pfd')}
                            className="hidden"
                            accept=".pdf,.doc,.docx,.txt,.md,.xlsx,.xls"
                          />
                        </label>
                      </div>
                      <button
                        onClick={removeValidationFile('pfd')}
                        disabled={!validationFiles.pfd}
                        className="p-2 hover:bg-accent rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className={`flex-1 p-4 border-2 border-dashed rounded-lg transition-colors ${
                        validationFiles.fmea ? 'border-primary bg-primary/5' : 'border-input hover:border-primary/50'
                      }`}>
                        <label className="flex flex-col items-center gap-2 cursor-pointer w-full">
                          <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                            validationFiles.fmea ? 'bg-primary/20' : 'bg-muted'
                          }`}>
                            <span className="text-2xl">⚠️</span>
                          </div>
                          <span className="text-sm font-medium">FMEA文件</span>
                          <span className="text-xs text-muted-foreground">必填</span>
                          {validationFiles.fmea && (
                            <span className="text-xs text-primary truncate max-w-xs">{validationFiles.fmea.name}</span>
                          )}
                          <input
                            ref={fmeaInputRef}
                            type="file"
                            onChange={handleValidationFileSelect('fmea')}
                            className="hidden"
                            accept=".pdf,.doc,.docx,.txt,.md,.xlsx,.xls"
                          />
                        </label>
                      </div>
                      <button
                        onClick={removeValidationFile('fmea')}
                        disabled={!validationFiles.fmea}
                        className="p-2 hover:bg-accent rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className={`flex-1 p-4 border-2 border-dashed rounded-lg transition-colors ${
                        validationFiles.controlPlan ? 'border-primary bg-primary/5' : 'border-input hover:border-primary/50'
                      }`}>
                        <label className="flex flex-col items-center gap-2 cursor-pointer w-full">
                          <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
                            validationFiles.controlPlan ? 'bg-primary/20' : 'bg-muted'
                          }`}>
                            <span className="text-2xl">✅</span>
                          </div>
                          <span className="text-sm font-medium">控制计划</span>
                          <span className="text-xs text-muted-foreground">可选</span>
                          {validationFiles.controlPlan && (
                            <span className="text-xs text-primary truncate max-w-xs">{validationFiles.controlPlan.name}</span>
                          )}
                          <input
                            ref={cpInputRef}
                            type="file"
                            onChange={handleValidationFileSelect('controlPlan')}
                            className="hidden"
                            accept=".pdf,.doc,.docx,.txt,.md,.xlsx,.xls"
                          />
                        </label>
                      </div>
                      <button
                        onClick={removeValidationFile('controlPlan')}
                        disabled={!validationFiles.controlPlan}
                        className="p-2 hover:bg-accent rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>

                  <button
                    onClick={handleValidateDocuments}
                    disabled={!allRequiredFilesSelected || validationLoading}
                    className={`w-full mt-6 py-3 rounded-lg font-medium flex items-center justify-center gap-2 transition-all ${
                      allRequiredFilesSelected && !validationLoading
                        ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                        : 'bg-muted text-muted-foreground cursor-not-allowed opacity-60'
                    }`}
                  >
                    {validationLoading ? (
                      <>
                        <Loader2 size={20} className="animate-spin" />
                        <span>校验中...</span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 size={20} />
                        <span>开始校验</span>
                      </>
                    )}
                  </button>
                </div>

                {validationResult && (
                  <div className="bg-card rounded-xl border border-border overflow-hidden">
                    <div className="p-4 border-b border-border flex items-center justify-between">
                      <h3 className="font-semibold flex items-center gap-2">
                        <span className="w-6 h-6 rounded-full bg-success text-success-foreground text-xs flex items-center justify-center">2</span>
                        校验结果
                      </h3>
                      <button
                        onClick={() => navigator.clipboard.writeText(validationResult.report)}
                        className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                      >
                        复制报告
                      </button>
                    </div>

                    <div className="p-4 space-y-4">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="bg-muted/50 rounded-lg p-3 text-center">
                          <div className="text-xl font-bold text-primary">{validationResult.data.summary.pfd_process_count}</div>
                          <div className="text-xs text-muted-foreground">PFD工序数</div>
                        </div>
                        <div className="bg-muted/50 rounded-lg p-3 text-center">
                          <div className="text-xl font-bold text-primary">{validationResult.data.summary.pfd_characteristic_count}</div>
                          <div className="text-xs text-muted-foreground">PFD特性数</div>
                        </div>
                        <div className="bg-muted/50 rounded-lg p-3 text-center">
                          <div className="text-xl font-bold text-primary">{validationResult.data.summary.fmea_failure_count}</div>
                          <div className="text-xs text-muted-foreground">FMEA失效数</div>
                        </div>
                        <div className="bg-muted/50 rounded-lg p-3 text-center">
                          <div className="text-xl font-bold text-primary">{validationResult.data.summary.control_plan_control_count}</div>
                          <div className="text-xs text-muted-foreground">管控措施数</div>
                        </div>
                      </div>

                      {validationResult.warnings && validationResult.warnings.length > 0 && (
                        <div className="bg-warning/10 border border-warning/30 rounded-lg p-4">
                          <div className="text-sm font-medium text-warning mb-2 flex items-center gap-2">
                            <AlertCircle size={16} />
                            提示
                          </div>
                          <ul className="text-xs text-warning/80 space-y-1">
                            {validationResult.warnings.map((warning, idx) => (
                              <li key={idx} className="flex items-start gap-2">
                                <ChevronRight size={12} className="mt-0.5" />
                                {warning}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {validationResult.data.checks.map((check, index) => (
                        <div key={index} className="border border-border rounded-lg overflow-hidden">
                          <div className="p-3 bg-muted/30 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium">{check.category}</span>
                              <ChevronRight size={16} className="text-muted-foreground" />
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {check.passed.length}已匹配 / {check.missing.length}缺失
                            </span>
                          </div>
                          <div className="p-3 space-y-2">
                            {check.passed.length > 0 && (
                              <div>
                                <div className="text-xs font-medium text-success mb-1 flex items-center gap-1">
                                  <CheckCircle2 size={12} />
                                  已匹配 ({check.passed.length})
                                </div>
                                <div className="space-y-1">
                                  {check.passed.map((item, idx) => (
                                    <div key={idx} className="text-xs text-muted-foreground ml-4">
                                      {item.pfd_item && (
                                        <span><strong className="text-foreground">PFD:</strong> {item.pfd_item}</span>
                                      )}
                                      {item.fmea_item && (
                                        <span><strong className="text-foreground">FMEA:</strong> {item.fmea_item}</span>
                                      )}
                                      {item.fmea_match && (
                                        <span className="ml-2 text-success">→ {item.fmea_match}</span>
                                      )}
                                      {item.control_plan_match && (
                                        <span className="ml-2 text-success">→ {item.control_plan_match}</span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {check.missing.length > 0 && (
                              <div className="mt-2">
                                <div className="text-xs font-medium text-warning mb-1 flex items-center gap-1">
                                  <AlertTriangle size={12} />
                                  缺失提示 ({check.missing.length})
                                </div>
                                <div className="space-y-1">
                                  {check.missing.map((item, idx) => {
                                    const key = `${index}-m-${idx}`;
                                    const isHighlighted = highlightedKeys.has(key);
                                    return (
                                      <div key={idx} className={`text-xs ml-4 ${isHighlighted ? 'text-red-500 font-bold' : 'text-muted-foreground'}`}>
                                        {item.pfd_item && (
                                          <span><strong className={isHighlighted ? 'text-red-600' : 'text-warning'}>PFD:</strong> {item.pfd_item}</span>
                                        )}
                                        {item.fmea_item && (
                                          <span><strong className={isHighlighted ? 'text-red-600' : 'text-warning'}>FMEA:</strong> {item.fmea_item}</span>
                                        )}
                                        {item.reason && (
                                          <span className="ml-2">({item.reason})</span>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}

                      <div className="mt-4 p-3 bg-muted/30 rounded-lg">
                        <div className="text-xs text-muted-foreground">
                          <strong>备注：</strong>本校验仅基于显性文本匹配，不涉及语义理解。校验结果仅供人工参考，请结合专业知识判断。
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                    <span className="text-3xl">💬</span>
                  </div>
                  <h2 className="text-xl font-semibold mb-2">开始新对话</h2>
                  <p className="text-muted-foreground max-w-md">
                    输入你的问题，AI 助手将为你解答。支持 Markdown
                    格式，包括代码高亮。
                  </p>
                </div>
              ) : (
                messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-4 animate-fade-in ${
                      message.role === "user" ? "flex-row-reverse" : ""
                    }`}
                  >
                    {/* 头像 */}
                    <div
                      className={`
                      flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center
                      ${
                        message.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-secondary-foreground"
                      }
                    `}
                    >
                      {message.role === "user" ? (
                        <User size={18} />
                      ) : (
                        <span className="text-sm">AI</span>
                      )}
                    </div>

                    {/* 消息内容 */}
                    <div
                      className={`flex-1 max-w-3xl ${message.role === "user" ? "text-right" : ""}`}
                    >
                      <div
                        className={`
                        inline-block px-4 py-3 rounded-2xl text-left
                        ${
                          message.role === "user"
                            ? "bg-primary text-primary-foreground rounded-tr-md"
                            : "bg-muted rounded-tl-md"
                        }
                      `}
                      >
                        <MarkdownRenderer content={message.content} />
                      </div>
                      <div
                        className={`text-xs text-muted-foreground mt-1 px-1 flex items-center gap-2 ${
                          message.role === "user" ? "justify-end" : "justify-start"
                        }`}
                      >
                        {new Date(message.timestamp).toLocaleTimeString("zh-CN", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                        {message.role === "assistant" &&
                          message.sources &&
                          message.sources.length > 0 && (
                            <SourceTooltip sources={message.sources} />
                          )}
                      </div>
                    </div>
                  </div>
                ))
              )}

              {/* 加载指示器 */}
              {isLoading && (
                <div className="flex gap-4 animate-fade-in">
                  <div className="flex-shrink-0 w-10 h-10 rounded-full bg-secondary flex items-center justify-center">
                    <span className="text-sm">AI</span>
                  </div>
                  <div className="flex-1 max-w-3xl">
                    <div className="inline-block px-4 py-3 rounded-2xl rounded-tl-md bg-muted">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Loader2 size={18} className="animate-spin" />
                        <span>正在思考...</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {validationMode !== 'validate' && (
          <div className="p-4 border-t border-border bg-card">
            {/* 文件预览栏 */}
            {selectedFile && (
              <div className="max-w-4xl mx-auto mb-2 px-4 py-2 bg-accent/30 rounded-lg flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm min-w-0">
                  <Paperclip size={16} className="text-muted-foreground flex-shrink-0" />
                  <span className="font-medium truncate">{selectedFile.name}</span>
                  <span className="text-xs text-muted-foreground flex-shrink-0">
                    ({(selectedFile.size / 1024).toFixed(1)} KB)
                  </span>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={handleScoreFile}
                    disabled={fileUploadLoading}
                    className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded
                             bg-background hover:bg-accent transition-colors
                             disabled:opacity-50 disabled:cursor-not-allowed"
                    title="对文件进行评分与摘要（不进入对话）"
                  >
                    <ClipboardCheck size={14} />
                    <span>评分+摘要</span>
                  </button>
                  <button
                    type="button"
                    onClick={handleUploadFileAndChat}
                    disabled={fileUploadLoading}
                    className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded
                             bg-primary text-primary-foreground hover:bg-primary/90 transition-colors
                             disabled:opacity-50 disabled:cursor-not-allowed"
                    title="上传文件并开启可追问的对话"
                  >
                    <MessageSquareText size={14} />
                    <span>上传并对话</span>
                  </button>
                  <button
                    onClick={removeSelectedFile}
                    className="p-1 hover:bg-accent rounded transition-colors"
                    aria-label="移除文件"
                  >
                    <Trash2 size={16} className="text-muted-foreground" />
                  </button>
                </div>
              </div>
            )}
            <div className="flex gap-3 items-end max-w-4xl mx-auto">
              <div className="flex-1 relative">
                {/* 文件上传按钮 */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isLoading || fileUploadLoading}
                  className="absolute left-3 top-1/2 -translate-y-1/2 p-1.5 text-muted-foreground 
             hover:text-foreground hover:bg-accent rounded-lg transition-colors
             disabled:opacity-50 disabled:cursor-not-allowed"
                  aria-label="上传文件"
                >
                  <Paperclip size={18} />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  onChange={handleFileSelect}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.pptx"
                />
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入你的问题... (Shift+Enter 换行，Enter 发送)"
                  className="w-full pl-12 pr-12 py-3 bg-background border border-input rounded-xl
                           resize-none focus:outline-none focus:ring-2 focus:ring-ring/50
                           placeholder:text-muted-foreground min-h-[48px] max-h-[200px]"
                  rows={1}
                  disabled={isLoading}
                />
              </div>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={
                  (!input.trim() && !selectedFile) ||
                  isLoading ||
                  fileUploadLoading
                }
                className={`
                  flex-shrink-0 p-3 rounded-xl transition-all
                  ${
                    (input.trim() || selectedFile) &&
                    !isLoading &&
                    !fileUploadLoading
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "bg-muted text-muted-foreground cursor-not-allowed"
                  }
                `}
              >
                {isLoading ? (
                  <Loader2 size={20} className="animate-spin" />
                ) : (
                  <Send size={20} />
                )}
              </button>
            </div>
            <p className="text-xs text-center text-muted-foreground mt-2">
              AI 助手可能会产生不准确的信息，请保持批判性思维
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

function SourceTooltip({ sources }: { sources: SourceSummary[] }) {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedSource, setExpandedSource] = useState<string | null>(null);
  const [sourceContent, setSourceContent] = useState<Map<string, string>>(new Map());
  const [loadingSource, setLoadingSource] = useState<string | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        tooltipRef.current &&
        !tooltipRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
        setExpandedSource(null);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const fetchSourceContent = async (source: string) => {
    if (sourceContent.has(source)) {
      setExpandedSource(expandedSource === source ? null : source);
      return;
    }
    setLoadingSource(source);
    try {
      const res = await fetch(`/kb/documents/${encodeURIComponent(source)}/content`);
      const data = await res.json();
      setSourceContent((prev) => new Map(prev).set(source, data.content));
    } catch (err) {
      console.error("获取文档内容失败:", err);
    }
    setLoadingSource(null);
    setExpandedSource(source);
  };

  return (
    <div className="relative inline-flex" ref={tooltipRef}>
      <button
        type="button"
        aria-label="参考来源"
        onClick={() => setIsOpen((prev) => !prev)}
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full 
                 transition-colors ${
                   isOpen
                     ? "text-primary bg-accent"
                     : "text-muted-foreground hover:text-foreground hover:bg-accent"
                 }`}
      >
        <FileSearch size={13} />
      </button>
      {isOpen && (
        <div
          className="pointer-events-auto absolute left-0 bottom-6 z-30 w-80 rounded-md border border-border 
                 bg-popover p-3 text-left text-xs text-popover-foreground shadow-lg"
        >
          <div className="font-medium mb-2">参考来源（点击查看内容）</div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {sources.map((source, index) => (
              <div key={`${source.source}-${index}`}>
                <div
                  onClick={() => fetchSourceContent(source.source)}
                  className="leading-relaxed cursor-pointer hover:text-primary transition-colors flex items-center gap-1"
                >
                  {index + 1}. {source.label || source.source}
                  {loadingSource === source.source && (
                    <span className="inline-block w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  )}
                  {expandedSource === source.source && !loadingSource && (
                    <span className="text-[10px] ml-auto">收起</span>
                  )}
                </div>
                {expandedSource === source.source && (
                  <div className="mt-2 p-2 bg-background rounded text-[12px] whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {loadingSource === source.source ? (
                      <span className="text-muted-foreground">加载中...</span>
                    ) : (
                      sourceContent.get(source.source) || "获取失败"
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
