import OpenAI from 'openai';
import type { ChatMessage, Language } from '../types';

let _client: OpenAI | null = null;

function getClient(apiKey: string): OpenAI {
  if (!_client || (_client as unknown as { apiKey: string }).apiKey !== apiKey) {
    _client = new OpenAI({ apiKey, dangerouslyAllowBrowser: true });
  }
  return _client;
}

export interface RefineRequest {
  userMessage: string;
  history: ChatMessage[];
  currentCode: Record<string, string>;
  operationName: string;
  language: Language;
}

export interface RefineResult {
  assistantMessage: string;
  updatedCode?: Record<string, string>;
}

const JAVA_SYSTEM_PROMPT = `You are an expert Java Spring Boot developer specialising in REST API services that wrap
N-Central SOAP/WSDL operations. Your role is to help refine and improve generated Java code.

When asked to improve code, return the improved file contents inside Markdown fenced code blocks with the file
type tag. Use the following tags so the UI can parse them:
- \`\`\`java:controller — for the Controller
- \`\`\`java:service — for the Service interface
- \`\`\`java:serviceImpl — for the ServiceImpl
- \`\`\`java:transformer — for the Transformer
- \`\`\`java:requestDto — for the RequestDTO
- \`\`\`java:responseDto — for the ResponseDTO

Only include files that changed. For explanations, use plain text outside the code blocks.
Follow these standards:
- Lombok annotations (@Data, @Builder, @Slf4j, @RequiredArgsConstructor)
- Spring Boot 3 + Jakarta EE namespace
- Bean Validation (@NotNull, @NotBlank, @Valid)
- SpringDoc OpenAPI annotations (@Operation, @Tag)
- Defensive null checks and proper error handling
- SLF4J logging`;

const PYTHON_SYSTEM_PROMPT = `You are an expert Python / FastAPI developer specialising in REST API services that wrap
N-Central SOAP/WSDL operations. Your role is to help refine and improve generated Python code.

When asked to improve code, return the improved file contents inside Markdown fenced code blocks with the file
type tag. Use the following tags so the UI can parse them:
- \`\`\`python:controller — for the FastAPI router
- \`\`\`python:service — for the abstract service base class
- \`\`\`python:serviceImpl — for the concrete service implementation
- \`\`\`python:transformer — for the Transformer
- \`\`\`python:requestDto — for the Pydantic request schema
- \`\`\`python:responseDto — for the Pydantic response schema

Only include files that changed. For explanations, use plain text outside the code blocks.
Follow these standards:
- FastAPI + Pydantic v2 BaseModel
- Dependency injection via FastAPI Depends()
- Python typing (Optional, list, etc.)
- zeep for SOAP client
- Standard logging module
- Async endpoint handlers`;

/** Parse the assistant reply and extract updated file content from tagged code blocks */
function parseCodeBlocks(text: string, lang: Language): Record<string, string> {
  const updates: Record<string, string> = {};
  const prefix = lang === 'java' ? 'java' : 'python';
  const regex = new RegExp(`\`\`\`${prefix}:(\\w+)\\n([\\s\\S]*?)\`\`\``, 'g');
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    const [, tag, code] = match;
    updates[tag] = code.trimEnd();
  }
  return updates;
}

export async function refineWithAI(
  apiKey: string,
  req: RefineRequest,
): Promise<RefineResult> {
  const client = getClient(apiKey);
  const systemPrompt = req.language === 'java' ? JAVA_SYSTEM_PROMPT : PYTHON_SYSTEM_PROMPT;
  const codeTag = req.language === 'java' ? 'java' : 'python';

  const systemWithCode = `${systemPrompt}

Current generated files for operation "${req.operationName}":

\`\`\`${codeTag}:controller
${req.currentCode.controller ?? ''}
\`\`\`

\`\`\`${codeTag}:service
${req.currentCode.serviceInterface ?? ''}
\`\`\`

\`\`\`${codeTag}:serviceImpl
${req.currentCode.serviceImpl ?? ''}
\`\`\`

\`\`\`${codeTag}:transformer
${req.currentCode.transformer ?? ''}
\`\`\`

\`\`\`${codeTag}:requestDto
${req.currentCode.requestDto ?? ''}
\`\`\`

\`\`\`${codeTag}:responseDto
${req.currentCode.responseDto ?? ''}
\`\`\``;

  const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [
    { role: 'system', content: systemWithCode },
    ...req.history.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
    })),
    { role: 'user', content: req.userMessage },
  ];

  const completion = await client.chat.completions.create({
    model: 'gpt-4o',
    messages,
    temperature: 0.3,
  });

  const assistantMessage = completion.choices[0]?.message?.content ?? '';
  const updatedCode = parseCodeBlocks(assistantMessage, req.language);

  return {
    assistantMessage,
    updatedCode: Object.keys(updatedCode).length ? updatedCode : undefined,
  };
}

export async function generateTestsWithAI(
  apiKey: string,
  operationName: string,
  currentCode: Record<string, string>,
  language: Language,
): Promise<{ unitTests: string; robotTests: string }> {
  const client = getClient(apiKey);
  const systemPrompt = language === 'java' ? JAVA_SYSTEM_PROMPT : PYTHON_SYSTEM_PROMPT;
  const codeTag = language === 'java' ? 'java' : 'python';
  const testFramework = language === 'java' ? 'JUnit 5 / Mockito' : 'pytest + unittest.mock';

  const prompt = `Generate comprehensive unit tests and Robot Framework tests for the ${operationName} ${
    language === 'java' ? 'Spring Boot' : 'FastAPI'
  } REST API.

Current implementation files:
${Object.entries(currentCode)
  .map(([k, v]) => `### ${k}\n\`\`\`${codeTag}\n${v}\n\`\`\``)
  .join('\n\n')}

Return:
1. ${testFramework} unit tests in a \`\`\`${codeTag}:unitTests block
2. Robot Framework tests in a \`\`\`robot:robotTests block

Follow the same code standards as the existing implementation.`;

  const completion = await client.chat.completions.create({
    model: 'gpt-4o',
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: prompt },
    ],
    temperature: 0.2,
  });

  const reply = completion.choices[0]?.message?.content ?? '';

  const unitMatch = new RegExp(`\`\`\`${codeTag}:unitTests\\n([\\s\\S]*?)\`\`\``).exec(reply);
  const robotMatch = /```robot:robotTests\n([\s\S]*?)```/.exec(reply);

  return {
    unitTests: unitMatch?.[1]?.trimEnd() ?? '',
    robotTests: robotMatch?.[1]?.trimEnd() ?? '',
  };
}
