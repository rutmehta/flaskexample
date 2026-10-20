from flask import Flask, jsonify, request

app = Flask(__name__, static_url_path='', static_folder='')

@app.route('/')
def root():
    return app.send_static_file('name.html')

@app.route('/health')
def health():
    return jsonify(status='ok')

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)

print("hi")