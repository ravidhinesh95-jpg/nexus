# NEXUS backend

The Flask app serves the frontend and its APIs from the same origin:

- `POST /api/register` — saves registration data and the uploaded college ID.
- `POST /api/contact` — saves a contact message and optional attachment.
- `GET /api/registration/<reg_id>` — supplies the confirmation page details.
- `/api/payment/*` — optional payment endpoints; configure Razorpay keys separately.

The current registration form saves the selected fee category but does not start
a payment checkout.

## Local setup

1. Create a MySQL database using `cyperx_db.sql` (or allow the server to create it).
2. Copy `.env.example` to `.env` and set the MySQL connection values for your machine.
3. From this `backend` folder, install dependencies and start the app:

   ```powershell
   py -m pip install -r requirements.txt
   py server.py
   ```

4. Open `http://127.0.0.1:3001` in your browser. Do not open the HTML files directly;
   the forms call the backend API on the same origin.

The registration password is stored as a password hash. Uploads are saved under
`backend/uploads` and are not served as public static files. Email and Razorpay
configuration are optional.

If MySQL already has an older schema, back up the database
before starting. The backend startup migrates its old registration/contact
columns to the current schema and keeps existing registration rows; passwords
and uploaded IDs for historical rows remain empty.
