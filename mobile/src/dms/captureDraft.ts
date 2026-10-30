import { CapturePhoto } from "../api/types";
import { generateIdempotencyKey } from "../sync/idempotency";

/** عکسی که گرفته شده ولی هنوز ارسال نشده (فقط در حافظهٔ صفحه). */
export interface DraftPhoto {
  uri: string;
  base64: string;
}

/** پیش‌نویس ارسال یک درخواست عکس‌برداری: کلید تکرارنشدن تا ارسال موفق ثابت است و با هر تغییر
 * عکس‌ها عوض می‌شود تا سرور مجموعهٔ جدید را ارسال تکراری حساب نکند. */
export interface CaptureDraft {
  requestId: number;
  maxPhotos: number;
  photos: DraftPhoto[];
  uploadKey: string;
}

export function newDraft(requestId: number, maxPhotos: number): CaptureDraft {
  return { requestId, maxPhotos: Math.max(1, maxPhotos), photos: [], uploadKey: generateIdempotencyKey() };
}

export function canAddPhoto(draft: CaptureDraft): boolean {
  return draft.photos.length < draft.maxPhotos;
}

export function addPhoto(draft: CaptureDraft, photo: DraftPhoto): CaptureDraft {
  if (!canAddPhoto(draft) || !photo.base64) return draft;
  return { ...draft, photos: [...draft.photos, photo], uploadKey: generateIdempotencyKey() };
}

export function removePhoto(draft: CaptureDraft, index: number): CaptureDraft {
  if (index < 0 || index >= draft.photos.length) return draft;
  return { ...draft, photos: draft.photos.filter((_, i) => i !== index), uploadKey: generateIdempotencyKey() };
}

export function replacePhoto(draft: CaptureDraft, index: number, photo: DraftPhoto): CaptureDraft {
  if (index < 0 || index >= draft.photos.length || !photo.base64) return draft;
  return { ...draft, photos: draft.photos.map((p, i) => (i === index ? photo : p)), uploadKey: generateIdempotencyKey() };
}

export function toPayload(draft: CaptureDraft): CapturePhoto[] {
  return draft.photos.map((photo, i) => ({ name: `photo-${i + 1}.jpg`, data_base64: photo.base64 }));
}

/** وضعیت‌هایی که هنوز می‌شود برایشان عکس فرستاد. */
export function isOpenStatus(status: string): boolean {
  return status === "PENDING" || status === "OPENED" || status === "CAPTURING" || status === "UPLOADING";
}
