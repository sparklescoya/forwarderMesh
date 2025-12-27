from quart import Quart, jsonify
app = Quart(__name__)

@app.route('/')
async def index():
    return jsonify({"message": "hello world"})

if __name__ == '__main__':
    app.run()