import { useRef, useState } from "react";
import { notifyCharacterMemoLimit } from "./characterMemo";

export function useCharacterImportForm(onImport: (file: File, name: string, profile: string) => Promise<unknown>, onNotice: (message: string) => void) {
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [importName, setImportName] = useState("");
  const [importProfile, setImportProfile] = useState("");
  const [wavImportOpen, setWavImportOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  async function importWav(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!referenceFile) return void onNotice("登録するWAVファイルを選んでください。");
    if (!importName.trim()) return void onNotice("キャラクター名を入力してください。");
    if (notifyCharacterMemoLimit(importProfile, onNotice)) return;
    await onImport(referenceFile, importName, importProfile);
    setReferenceFile(null);
    setImportName("");
    setImportProfile("");
    setWavImportOpen(false);
    if (fileInput.current) fileInput.current.value = "";
  }
  return { referenceFile, setReferenceFile, importName, setImportName, importProfile, setImportProfile, wavImportOpen, setWavImportOpen, fileInput, importWav };
}
