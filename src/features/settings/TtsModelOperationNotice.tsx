import { CenteredNotice } from "../shared/CenteredNotice";

export function TtsModelOperationNotice({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <CenteredNotice tone="danger">
      <strong>{message}</strong>
      <span>完了するまでお待ちください。</span>
    </CenteredNotice>
  );
}
