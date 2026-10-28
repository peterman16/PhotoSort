# PhotoSort — Domain Glossary

**Card**
The camera's memory card (or any source drive) holding a shoot's JPGs and RAWs straight from the camera.

**Library**
The place all Shoot folders live, organised by year. By default, the Pictures folder; usually set to an external drive.

**Shoot**
One batch of photos imported and culled together, named by the capture date of its first photo (`YYYY_MM_DD`, with an optional description).

**Shoot folder**
The folder on the computer where a shoot lives after import. An existing folder of JPGs can also be opened as a Shoot; it then has no recorded Card.

**Cull**
The pass where the photographer reviews a shoot's JPGs and marks each one. "Sorting" in casual speech means culling.

**Pick**
A JPG marked as a keeper. Its Companion RAW will be exported.

**Reject**
A JPG marked as unwanted. Rejects can be filtered out of view and, separately, deleted (to the Recycle Bin, never permanently). Deleting a Reject never touches the Card.

**Unmarked**
A JPG that has been neither picked nor rejected yet.

**Import**
Bringing JPGs from the Card into a Shoot folder. RAWs stay on the Card until Export. Photos already in a known Shoot are skipped.

**Filmstrip view**
The default way to Cull: one large photo with a strip of neighbouring thumbnails.

**Grid view**
The alternative way to Cull: many thumbnails at once, from which a photo can be opened in Filmstrip view.

**Auto-advance**
A switchable mode in which marking a photo as a Pick or Reject moves on to the next photo.

**Filter**
Which photos are shown during the Cull: all, hide Rejects, Picks only, or Unmarked only. Filtering hides; it never deletes.

**Companion RAW**
The RAW file shot alongside a JPG, identified by an identical filename stem (`IMG_1234.JPG` ↔ `IMG_1234.CR3`). Canon `.CR3` (R8) and `.CR2` (EOS 70D); others can be added. If two cameras produce the same filename in one Shoot, the later one gets a camera tag (`IMG_3988_70D`) on both its JPG and its RAW.

**Export**
Copying the Companion RAWs of all Picks from the Card into the Shoot folder. Copies, never moves. Afterwards the photographer is asked whether to remove the Picks' JPGs, leaving a Shoot folder of RAWs only (the default).

**Exported (Shoot)**
A Shoot whose Export has completed. Its Picks' RAWs are in the Shoot folder, and its marks are kept as a record.

**Batch rename**
An optional step of Export that gives the Picks' RAWs new names in capture order (by default `YYYY_MM_DD[_description]_NNN`). The original camera filenames are remembered.
