import { listDocuments } from '@/lib/documents';
import UploadForm from './UploadForm';

// Upload screen (Task 2.1, route /upload, Form type per UI_SURFACE.md).
// No Vendor field — the app identifies vendor during extraction (Task 3.1),
// not the user here (ARCHITECTURE.md D-L amendment). Save behaviour: stay on
// page with a confirmation toast (resolved default), not a redirect.
export default function UploadPage() {
  const documents = listDocuments();

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">
          <div className="eyebrow">Upload</div>
          <h1>Upload statement</h1>
        </div>
      </div>
      <div className="content">
        <UploadForm initialDocuments={documents} />
      </div>
    </>
  );
}
