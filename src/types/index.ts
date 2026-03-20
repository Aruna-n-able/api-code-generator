export interface WsdlField {
  name: string;
  type: string;
  required: boolean;
  maxOccurs?: string;
  documentation?: string;
}

export interface WsdlOperation {
  name: string;
  documentation?: string;
  inputMessageName?: string;
  outputMessageName?: string;
  inputFields: WsdlField[];
  outputFields: WsdlField[];
}

export interface WsdlInfo {
  serviceName: string;
  portName?: string;
  targetNamespace?: string;
  operations: WsdlOperation[];
}

export interface GeneratedFiles {
  requestDto: string;
  responseDto: string;
  serviceInterface: string;
  serviceImpl: string;
  transformer: string;
  controller: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type CodeTab =
  | 'requestDto'
  | 'responseDto'
  | 'serviceInterface'
  | 'serviceImpl'
  | 'transformer'
  | 'controller';

export type TestTab = 'unit' | 'robot';
