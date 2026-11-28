import { useRef, useState } from "react";
import { useInlineValidation } from "../shared/useInlineValidation";
import { reportCharacterMemoLimit } from "./characterMemo";

export function useCharacterImportForm(onImport: (file: File, name: string, profile: string) => Promise<unknown>) {
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [importName, setImportName] = useState("");
  const [importProfile, setImportProfile] = useState("");
  const [wavImportOpen, setWavImportOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const importValidation = useInlineValidation();
  async function importWav(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!referenceFile) return void importValidation.report("登録するWAVファイルを選んでください。", "referenceFile");
    if (!importName.trim()) return void importValidation.report("キャラクター名を入力してください。", "importName");
    if (reportCharacterMemoLimit(importProfile, importValidation.report, "importProfile")) return;
    await onImport(referenceFile, importName, importProfile);
    setReferenceFile(null);
    setImportName("");
    setImportProfile("");
    setWavImportOpen(false);
    if (fileInput.current) fileInput.current.value = "";
  }
  return {
    referenceFile,
    setReferenceFile: (file: File | null) => (setReferenceFile(file), importValidation.clear("referenceFile")),
    importName,
    setImportName: (value: string) => (setImportName(value), importValidation.clear("importName")),
    importProfile,
    setImportProfile: (value: string) => (setImportProfile(value), importValidation.clear("importProfile")),
    wavImportOpen,
    setWavImportOpen: (open: boolean) => (setWavImportOpen(open), importValidation.clear()),
    fileInput,
    importWav,
    importValidation,
  };
}
