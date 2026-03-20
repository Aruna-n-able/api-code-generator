import { XMLParser } from 'fast-xml-parser';
import type { WsdlInfo, WsdlOperation, WsdlField } from '../types';

// XSD primitive types → Java types
const XSD_TO_JAVA: Record<string, string> = {
  string: 'String',
  normalizedString: 'String',
  token: 'String',
  int: 'Integer',
  integer: 'Integer',
  long: 'Long',
  short: 'Short',
  byte: 'Byte',
  double: 'Double',
  float: 'Float',
  decimal: 'BigDecimal',
  boolean: 'Boolean',
  dateTime: 'LocalDateTime',
  date: 'LocalDate',
  time: 'LocalTime',
  base64Binary: 'byte[]',
  anyURI: 'String',
  anyType: 'Object',
};

function resolveLocalName(qname: string): string {
  if (!qname) return '';
  const idx = qname.indexOf(':');
  return idx >= 0 ? qname.slice(idx + 1) : qname;
}

function xsdToJava(xsdType: string): string {
  const local = resolveLocalName(xsdType);
  return XSD_TO_JAVA[local] ?? 'String';
}

/** Unwrap a value that may be an array (from isArray) or a plain object */
function unwrapSingle(val: unknown): Record<string, unknown> | null {
  if (!val) return null;
  if (Array.isArray(val)) return val.length > 0 ? (val[0] as Record<string, unknown>) : null;
  if (typeof val === 'object') return val as Record<string, unknown>;
  return null;
}

/** Recursively flatten all xs:element nodes from a sequence/complexType subtree */
function extractSequenceElements(node: Record<string, unknown>): WsdlField[] {
  const ELEMENT_KEYS = ['xs:element', 'xsd:element', 'element'];
  const SEQUENCE_KEYS = ['xs:sequence', 'xsd:sequence', 'sequence'];
  const ALL_KEYS = ['xs:all', 'xsd:all', 'all'];
  const COMPLEX_KEYS = ['xs:complexType', 'xsd:complexType', 'complexType'];

  // Dive into complexType (unwrap in case it's an array)
  for (const key of COMPLEX_KEYS) {
    const ct = unwrapSingle(node[key]);
    if (ct) return extractSequenceElements(ct);
  }

  // Collect elements from sequence / all directly
  for (const key of [...SEQUENCE_KEYS, ...ALL_KEYS]) {
    const seqRaw = node[key];
    if (!seqRaw) continue;
    // sequence may itself be an array (unlikely but defensive)
    const seqNode = unwrapSingle(seqRaw);
    if (!seqNode) continue;

    const fields: WsdlField[] = [];
    for (const ek of ELEMENT_KEYS) {
      if (!seqNode[ek]) continue;
      const rawEls = seqNode[ek];
      const els: unknown[] = Array.isArray(rawEls) ? rawEls : [rawEls];
      for (const el of els) {
        const e = el as Record<string, unknown>;
        const name = resolveLocalName((e['@_name'] ?? e['@_ref'] ?? '') as string);
        if (!name) continue;

        const rawType = (e['@_type'] ?? '') as string;
        const javaType = rawType ? xsdToJava(rawType) : 'String';
        const minOccurs = (e['@_minOccurs'] ?? '1') as string;
        const maxOccurs = (e['@_maxOccurs'] ?? '1') as string;
        const nillable = e['@_nillable'];

        const nestedComplexKey = COMPLEX_KEYS.find((k) => e[k]);
        const fieldType = nestedComplexKey ? 'Object' : javaType;

        fields.push({
          name,
          type: maxOccurs === 'unbounded' ? `List<${fieldType}>` : fieldType,
          required:
            minOccurs !== '0' &&
            nillable !== true &&
            nillable !== 'true' &&
            nillable !== 1,
          maxOccurs: maxOccurs !== '1' ? maxOccurs : undefined,
        });
      }
    }
    return fields;
  }

  return [];
}

/** Build a map from element/complexType name → fields */
function buildSchemaMap(schema: unknown): Record<string, WsdlField[]> {
  if (!schema || typeof schema !== 'object') return {};
  const s = schema as Record<string, unknown>;
  const map: Record<string, WsdlField[]> = {};

  const ELEMENT_KEYS = ['xs:element', 'xsd:element', 'element'];
  const COMPLEX_KEYS = ['xs:complexType', 'xsd:complexType', 'complexType'];

  // Top-level elements
  for (const key of ELEMENT_KEYS) {
    if (!s[key]) continue;
    const arr: unknown[] = Array.isArray(s[key]) ? (s[key] as unknown[]) : [s[key]];
    for (const el of arr) {
      const e = el as Record<string, unknown>;
      const name = (e['@_name'] ?? '') as string;
      if (name) {
        map[name] = extractSequenceElements(e);
      }
    }
  }

  // Top-level complex types
  for (const key of COMPLEX_KEYS) {
    if (!s[key]) continue;
    const arr: unknown[] = Array.isArray(s[key]) ? (s[key] as unknown[]) : [s[key]];
    for (const ct of arr) {
      const c = ct as Record<string, unknown>;
      const name = (c['@_name'] ?? '') as string;
      if (name) {
        map[name] = extractSequenceElements(c);
      }
    }
  }

  return map;
}

/** Build a map from message name → list of WsdlField */
function buildMessageMap(
  defs: Record<string, unknown>,
  schemaMap: Record<string, WsdlField[]>,
): Record<string, { messageName: string; fields: WsdlField[] }> {
  const map: Record<string, { messageName: string; fields: WsdlField[] }> = {};
  const MSG_KEYS = ['wsdl:message', 'message'];

  for (const key of MSG_KEYS) {
    if (!defs[key]) continue;
    const msgs: unknown[] = Array.isArray(defs[key])
      ? (defs[key] as unknown[])
      : [defs[key]];

    for (const msg of msgs) {
      const m = msg as Record<string, unknown>;
      const msgName = (m['@_name'] ?? '') as string;
      if (!msgName) continue;

      const fields: WsdlField[] = [];
      const PART_KEYS = ['wsdl:part', 'part'];

      for (const pk of PART_KEYS) {
        if (!m[pk]) continue;
        const parts: unknown[] = Array.isArray(m[pk])
          ? (m[pk] as unknown[])
          : [m[pk]];
        for (const part of parts) {
          const p = part as Record<string, unknown>;
          // Part may reference an element or a type
          const elementRef = resolveLocalName((p['@_element'] ?? '') as string);
          const typeRef = (p['@_type'] ?? '') as string;

          if (elementRef && schemaMap[elementRef]) {
            // Element reference - expand its children
            fields.push(...schemaMap[elementRef]);
          } else if (elementRef) {
            // Unknown element ref - use as a single field
            fields.push({ name: elementRef, type: 'Object', required: true });
          } else if (typeRef) {
            // Typed part - use the part name as field
            const partName = (p['@_name'] ?? 'parameters') as string;
            fields.push({ name: partName, type: xsdToJava(typeRef), required: true });
          }
        }
      }

      map[msgName] = { messageName: msgName, fields };
    }
  }
  return map;
}

export function parseWsdl(xmlContent: string): WsdlInfo {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    isArray: (name) =>
      [
        'wsdl:message',
        'message',
        'wsdl:part',
        'part',
        'wsdl:operation',
        'operation',
        'xs:element',
        'xsd:element',
        'element',
      ].includes(name),
    textNodeName: '#text',
    parseAttributeValue: false,
    trimValues: true,
    allowBooleanAttributes: true,
  });

  const parsed = parser.parse(xmlContent) as Record<string, unknown>;

  // Locate definitions root (may be wsdl:definitions or definitions)
  const defs = (
    parsed['wsdl:definitions'] ??
    parsed['definitions'] ??
    parsed
  ) as Record<string, unknown>;

  const targetNamespace = (defs['@_targetNamespace'] ?? '') as string;

  // Service name
  const svcNode = (defs['wsdl:service'] ?? defs['service']) as
    | Record<string, unknown>
    | undefined;
  const serviceName =
    (svcNode?.['@_name'] as string | undefined) ?? 'NCentralService';

  const portNode = svcNode
    ? ((svcNode['wsdl:port'] ?? svcNode['port']) as Record<string, unknown> | undefined)
    : undefined;
  const portName = portNode?.['@_name'] as string | undefined;

  // Schema map
  const typesNode = (defs['wsdl:types'] ?? defs['types']) as
    | Record<string, unknown>
    | undefined;
  const schemaNode = typesNode
    ? ((typesNode['xs:schema'] ??
        typesNode['xsd:schema'] ??
        typesNode['schema']) as unknown)
    : null;
  const schemaMap = buildSchemaMap(schemaNode);

  // Message map
  const messageMap = buildMessageMap(defs, schemaMap);

  // Port type operations
  const portTypeNode = (defs['wsdl:portType'] ?? defs['portType']) as
    | Record<string, unknown>
    | undefined;

  const rawOps = portTypeNode
    ? ((portTypeNode['wsdl:operation'] ?? portTypeNode['operation']) as unknown[])
    : [];

  const opsArr: unknown[] = Array.isArray(rawOps)
    ? rawOps
    : rawOps
      ? [rawOps]
      : [];

  const operations: WsdlOperation[] = opsArr.map((op) => {
    const o = op as Record<string, unknown>;
    const name = (o['@_name'] ?? '') as string;

    const docNode = o['wsdl:documentation'] ?? o['documentation'];
    const documentation =
      typeof docNode === 'string'
        ? docNode
        : (docNode as Record<string, unknown> | undefined)?.['#text'] as
            | string
            | undefined;

    const inputNode = (o['wsdl:input'] ?? o['input']) as
      | Record<string, unknown>
      | undefined;
    const outputNode = (o['wsdl:output'] ?? o['output']) as
      | Record<string, unknown>
      | undefined;

    const inputMsgRef = resolveLocalName(
      (inputNode?.['@_message'] ?? '') as string,
    );
    const outputMsgRef = resolveLocalName(
      (outputNode?.['@_message'] ?? '') as string,
    );

    const inputEntry = inputMsgRef ? messageMap[inputMsgRef] : undefined;
    const outputEntry = outputMsgRef ? messageMap[outputMsgRef] : undefined;

    return {
      name,
      documentation,
      inputMessageName: inputMsgRef || undefined,
      outputMessageName: outputMsgRef || undefined,
      inputFields: inputEntry?.fields ?? [],
      outputFields: outputEntry?.fields ?? [],
    };
  });

  return { serviceName, portName, targetNamespace, operations };
}

/** Validate that a string looks like WSDL XML */
export function isValidWsdl(content: string): boolean {
  const trimmed = content.trim();
  return (
    (trimmed.includes('wsdl:definitions') || trimmed.includes('<definitions')) &&
    trimmed.startsWith('<')
  );
}
