import OpenAI from 'openai';
import type { ChatMessage } from '../types';

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
}

export interface RefineResult {
  assistantMessage: string;
  updatedCode?: Record<string, string>;
}

const SYSTEM_PROMPT = `You are an expert Java Spring Boot developer specialising in REST API services that wrap
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

/** Parse the assistant reply and extract updated file content from tagged code blocks */
function parseCodeBlocks(text: string): Record<string, string> {
  const updates: Record<string, string> = {};
  const regex = /```java:(\w+)\n([\s\S]*?)```/g;
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

  const systemWithCode = `${SYSTEM_PROMPT}

Current generated files for operation "${req.operationName}":

\`\`\`java:controller
${req.currentCode.controller ?? ''}
\`\`\`

\`\`\`java:service
${req.currentCode.serviceInterface ?? ''}
\`\`\`

\`\`\`java:serviceImpl
${req.currentCode.serviceImpl ?? ''}
\`\`\`

\`\`\`java:transformer
${req.currentCode.transformer ?? ''}
\`\`\`

\`\`\`java:requestDto
${req.currentCode.requestDto ?? ''}
\`\`\`

\`\`\`java:responseDto
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
  const updatedCode = parseCodeBlocks(assistantMessage);

  return {
    assistantMessage,
    updatedCode: Object.keys(updatedCode).length ? updatedCode : undefined,
  };
}

export async function generateTestsWithAI(
  apiKey: string,
  operationName: string,
  currentCode: Record<string, string>,
): Promise<{ unitTests: string; robotTests: string }> {
  const client = getClient(apiKey);

  const prompt = `Generate comprehensive unit tests and Robot Framework tests for the ${operationName} Spring Boot REST API.

Current implementation files:
${Object.entries(currentCode)
  .map(([k, v]) => `### ${k}\n\`\`\`java\n${v}\n\`\`\``)
  .join('\n\n')}

Return:
1. JUnit 5 / Mockito unit tests in a \`\`\`java:unitTests block
2. Robot Framework tests in a \`\`\`robot:robotTests block

Follow the same code standards as the existing implementation.`;

  const completion = await client.chat.completions.create({
    model: 'gpt-4o',
    messages: [
      { role: 'system', content: SYSTEM_PROMPT },
      { role: 'user', content: prompt },
    ],
    temperature: 0.2,
  });

  const reply = completion.choices[0]?.message?.content ?? '';

  const javaMatch = /```java:unitTests\n([\s\S]*?)```/.exec(reply);
  const robotMatch = /```robot:robotTests\n([\s\S]*?)```/.exec(reply);

  return {
    unitTests: javaMatch?.[1]?.trimEnd() ?? '',
    robotTests: robotMatch?.[1]?.trimEnd() ?? '',
  };
}
