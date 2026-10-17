/**
 * Patient-half text. Every string the patient sees is in their own script at
 * 24pt or more (docs/01 §2); icons carry the meaning for anyone who cannot read
 * at all. Nothing here is clinical — doses come only from confirmed RxLine
 * fields, never from this file.
 *
 * NEEDS-NATIVE-REVIEW: `content-eval` owns clinical phrasing; these are UI chrome
 * strings only.
 */

import type { PatientLanguage } from "./types";

export interface PatientStrings {
  label: string;
  nativeName: string;
  /** Tailwind font stack class, so each script gets a face that renders it. */
  fontClass: string;
  holdToTalk: string;
  listening: string;
  agentSpeaking: string;
  yourMedicines: string;
  scanForVoiceNote: string;
  morning: string;
  afternoon: string;
  night: string;
  beforeFood: string;
  afterFood: string;
  withFood: string;
  days: string;
  tablet: string;
  /** "half", for the half-tablet glyph on the picture card. */
  half: string;
  spoon: string;
  drop: string;
  injection: string;
  waitingForDoctor: string;
}

const EN_FALLBACK: PatientStrings = {
  label: "English",
  nativeName: "English",
  fontClass: "font-sans",
  holdToTalk: "HOLD TO TALK",
  listening: "Listening…",
  agentSpeaking: "Speaking…",
  yourMedicines: "Your medicines",
  scanForVoiceNote: "Scan to hear this again",
  morning: "Morning",
  afternoon: "Afternoon",
  night: "Night",
  beforeFood: "Before food",
  afterFood: "After food",
  withFood: "With food",
  days: "days",
  tablet: "tablet",
  half: "half",
  spoon: "spoon",
  drop: "drop",
  injection: "injection",
  waitingForDoctor: "Please wait",
};

export const PATIENT_STRINGS: Record<"ta" | "kn" | "hi", PatientStrings> = {
  ta: {
    label: "Tamil",
    nativeName: "தமிழ்",
    fontClass: "font-tamil",
    holdToTalk: "பேச அழுத்திப் பிடிக்கவும்",
    listening: "கேட்கிறேன்…",
    agentSpeaking: "பேசுகிறேன்…",
    yourMedicines: "உங்கள் மருந்துகள்",
    scanForVoiceNote: "மீண்டும் கேட்க ஸ்கேன் செய்யுங்கள்",
    morning: "காலை",
    afternoon: "மதியம்",
    night: "இரவு",
    beforeFood: "சாப்பிடும் முன்",
    afterFood: "சாப்பிட்ட பிறகு",
    withFood: "உணவுடன்",
    days: "நாட்கள்",
    tablet: "மாத்திரை",
    half: "அரை",
    spoon: "ஸ்பூன்",
    drop: "சொட்டு",
    injection: "ஊசி",
    waitingForDoctor: "தயவுசெய்து காத்திருங்கள்",
  },
  kn: {
    label: "Kannada",
    nativeName: "ಕನ್ನಡ",
    fontClass: "font-kannada",
    holdToTalk: "ಮಾತನಾಡಲು ಒತ್ತಿ ಹಿಡಿಯಿರಿ",
    listening: "ಕೇಳುತ್ತಿದ್ದೇನೆ…",
    agentSpeaking: "ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ…",
    yourMedicines: "ನಿಮ್ಮ ಔಷಧಿಗಳು",
    scanForVoiceNote: "ಮತ್ತೆ ಕೇಳಲು ಸ್ಕ್ಯಾನ್ ಮಾಡಿ",
    morning: "ಬೆಳಿಗ್ಗೆ",
    afternoon: "ಮಧ್ಯಾಹ್ನ",
    night: "ರಾತ್ರಿ",
    beforeFood: "ಊಟಕ್ಕೆ ಮೊದಲು",
    afterFood: "ಊಟದ ನಂತರ",
    withFood: "ಊಟದ ಜೊತೆ",
    days: "ದಿನಗಳು",
    tablet: "ಮಾತ್ರೆ",
    half: "ಅರ್ಧ",
    spoon: "ಚಮಚ",
    drop: "ಹನಿ",
    injection: "ಚುಚ್ಚುಮದ್ದು",
    waitingForDoctor: "ದಯವಿಟ್ಟು ಕಾಯಿರಿ",
  },
  hi: {
    label: "Hindi",
    nativeName: "हिन्दी",
    fontClass: "font-devanagari",
    holdToTalk: "बोलने के लिए दबाकर रखें",
    listening: "सुन रहा हूँ…",
    agentSpeaking: "बोल रहा हूँ…",
    yourMedicines: "आपकी दवाइयाँ",
    scanForVoiceNote: "दोबारा सुनने के लिए स्कैन करें",
    morning: "सुबह",
    afternoon: "दोपहर",
    night: "रात",
    beforeFood: "खाने से पहले",
    afterFood: "खाने के बाद",
    withFood: "खाने के साथ",
    days: "दिन",
    tablet: "गोली",
    half: "आधी",
    spoon: "चम्मच",
    drop: "बूँद",
    injection: "इंजेक्शन",
    waitingForDoctor: "कृपया प्रतीक्षा करें",
  },
};

export function stringsFor(lang: PatientLanguage): PatientStrings {
  if (lang === "ta" || lang === "kn" || lang === "hi") return PATIENT_STRINGS[lang];
  return EN_FALLBACK;
}

/** The language chips staff can tap — the one-tap override of docs/01 §1. */
export const LANGUAGE_CHIPS: { lang: "ta" | "kn" | "hi"; native: string; label: string }[] = [
  { lang: "ta", native: "தமிழ்", label: "Tamil" },
  { lang: "kn", native: "ಕನ್ನಡ", label: "Kannada" },
  { lang: "hi", native: "हिन्दी", label: "Hindi" },
];
