from flask import request, jsonify
from app import app, db, jwt
from models import User, Post, Comment
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user or not user.is_admin:  # Assuming you might want to add admin checks later
            return jsonify({'message': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

# User Registration
@app.route('/register', methods=['POST'])
def register():
    if not request.is_json:
        return jsonify({"msg": "Missing JSON in request"}), 400
        
    data = request.get_json()
    
    if not data.get('username') or not data.get('password'):
        return jsonify({"msg": "Missing username or password"}), 400
    
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"msg": "Username already exists"}), 400
    
    try:
        hashed_password = generate_password_hash(data['password'], method='pbkdf2:sha256')
        new_user = User(username=data['username'], password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        # Ensure we have a valid user ID
        if not new_user.id:
            db.session.rollback()
            return jsonify({"msg": "Error creating user account"}), 500
            
        # Create access token with user_id as integer
        access_token = create_access_token(identity=int(new_user.id))
        
        return jsonify({
            "msg": "User registered successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": new_user.id,
                "username": new_user.username
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": "Error creating user"}), 500

# In routes.py, update the login function
@app.route('/login', methods=['POST'])
def login():
    if not request.is_json:
        return jsonify({"msg": "Missing JSON in request"}), 400
        
    data = request.get_json()
    
    if not data.get('username') or not data.get('password'):
        return jsonify({"msg": "Missing username or password"}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not check_password_hash(user.password, data['password']):
        return jsonify({"msg": "Bad username or password"}), 401
    
    try:
        if not user.id:
            return jsonify({"msg": "Invalid user ID"}), 500
            
        # Create access token with user_id as integer
        access_token = create_access_token(identity=user.id)
        
        return jsonify({
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username
            }
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error in login: {str(e)}")
        return jsonify({"msg": "Internal server error during login"}), 500

# Create Post
@app.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    if not request.is_json:
        return jsonify({"message": "Missing JSON in request"}), 400
        
    data = request.get_json()
    current_user_id = get_jwt_identity()
    
    # Validate required fields
    required_fields = ['title', 'content']
    missing_fields = [field for field in required_fields if not data.get(field)]
    
    if missing_fields:
        return jsonify({
            "message": f"Missing required fields: {', '.join(missing_fields)}"
        }), 422
    
    try:
        # Create the post
        new_post = Post(
            title=data['title'],
            content=data['content'],
            excerpt=data.get('excerpt', data['content'][:200] + '...' if len(data['content']) > 200 else data['content']),
            featured_image=data.get('featured_image'),
            is_published=data.get('is_published', False),
            user_id=current_user_id
        )
        
        # Handle tags if provided
        if 'tags' in data and isinstance(data['tags'], list):
            for tag_name in data['tags']:
                if not tag_name.strip():
                    continue
                    
                # Find existing tag or create new one
                tag = Tag.query.filter_by(name=tag_name.lower()).first()
                if not tag:
                    tag = Tag(name=tag_name.lower())
                    db.session.add(tag)
                new_post.tags.append(tag)
        
        db.session.add(new_post)
        db.session.commit()
        
        # Prepare response
        post_data = {
            "id": new_post.id,
            "title": new_post.title,
            "slug": new_post.slug,
            "excerpt": new_post.excerpt,
            "content": new_post.content,
            "featured_image": new_post.featured_image,
            "is_published": new_post.is_published,
            "date_posted": new_post.date_posted.isoformat(),
            "last_modified": new_post.last_modified.isoformat(),
            "user_id": new_post.user_id,
            "author": new_post.author.username,
            "tags": [tag.name for tag in new_post.tags]
        }
        
        return jsonify({
            "message": "Post created successfully",
            "post": post_data
        }), 201
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating post: {str(e)}")
        return jsonify({"message": "Error creating post"}), 500

# Get All Posts
@app.route('/posts', methods=['GET'])
def get_all_posts():
    try:
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Filters
        published_only = request.args.get('published_only', 'true').lower() == 'true'
        author_id = request.args.get('author_id', type=int)
        tag = request.args.get('tag')
        search = request.args.get('search')
        
        # Base query
        query = Post.query
        
        # Apply filters
        if published_only:
            query = query.filter_by(is_published=True)
            
        if author_id:
            query = query.filter_by(user_id=author_id)
            
        if tag:
            query = query.join(Post.tags).filter(Tag.name.ilike(f'%{tag}%'))
            
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                db.or_(
                    Post.title.ilike(search_term),
                    Post.content.ilike(search_term),
                    Post.excerpt.ilike(search_term)
                )
            )
        
        # Order and paginate
        posts = query.order_by(Post.date_posted.desc())\
                    .paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        output = []
        for post in posts.items:
            post_data = {
                'id': post.id,
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt,
                'featured_image': post.featured_image,
                'is_published': post.is_published,
                'date_posted': post.date_posted.isoformat(),
                'last_modified': post.last_modified.isoformat(),
                'author': post.author.username,
                'author_id': post.user_id,
                'comment_count': len(post.comments),
                'tags': [tag.name for tag in post.tags]
            }
            output.append(post_data)
        
        # Add pagination metadata
        pagination = {
            'page': page,
            'per_page': per_page,
            'total_pages': posts.pages,
            'total_items': posts.total,
            'has_next': posts.has_next,
            'has_prev': posts.has_prev
        }
        
        return jsonify({
            'posts': output,
            'pagination': pagination
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching posts: {str(e)}")
        return jsonify({"message": "Error fetching posts"}), 500

# Get Single Post
@app.route('/posts/<int:post_id>', methods=['GET'])
@app.route('/posts/<string:post_slug>', methods=['GET'])
def get_post(post_id=None, post_slug=None):
    try:
        # Find post by ID or slug
        if post_id:
            post = Post.query.get_or_404(post_id)
        else:
            post = Post.query.filter_by(slug=post_slug).first_or_404()
            
        # Only show published posts to non-owners unless explicitly requested
        current_user_id = get_jwt_identity() if 'Authorization' in request.headers else None
        if post.is_published is False and (not current_user_id or current_user_id != post.user_id):
            return jsonify({"message": "Post not found"}), 404
            
        # Format comments
        comments = []
        for comment in post.comments:
            comments.append({
                'id': comment.id,
                'content': comment.content,
                'date_posted': comment.date_posted.isoformat(),
                'author': {
                    'id': comment.comment_author.id,
                    'username': comment.comment_author.username
                }
            })
        
        # Format tags
        tags = [{'id': tag.id, 'name': tag.name, 'slug': tag.slug} for tag in post.tags]
        
        # Format response
        post_data = {
            'id': post.id,
            'title': post.title,
            'slug': post.slug,
            'excerpt': post.excerpt,
            'content': post.content,
            'featured_image': post.featured_image,
            'is_published': post.is_published,
            'date_posted': post.date_posted.isoformat(),
            'last_modified': post.last_modified.isoformat(),
            'author': {
                'id': post.author.id,
                'username': post.author.username
            },
            'comment_count': len(post.comments),
            'comments': comments,
            'tags': tags
        }
        
        return jsonify(post_data), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching post: {str(e)}")
        return jsonify({"message": "Error fetching post"}), 500

# Get User's Posts
@app.route('/my_posts', methods=['GET'])
@jwt_required()
def get_my_posts():
    try:
        current_user_id = get_jwt_identity()
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Filters
        published_only = request.args.get('published_only', 'false').lower() == 'true'
        search = request.args.get('search')
        tag = request.args.get('tag')
        
        # Base query
        query = Post.query.filter_by(user_id=current_user_id)
        
        # Apply filters
        if published_only:
            query = query.filter_by(is_published=True)
            
        if tag:
            query = query.join(Post.tags).filter(Tag.name.ilike(f'%{tag}%'))
            
        if search:
            search_term = f'%{search}%'
            query = query.filter(
                db.or_(
                    Post.title.ilike(search_term),
                    Post.content.ilike(search_term),
                    Post.excerpt.ilike(search_term)
                )
            )
        
        # Order and paginate
        posts = query.order_by(Post.date_posted.desc())\
                    .paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        output = []
        for post in posts.items:
            post_data = {
                'id': post.id,
                'title': post.title,
                'slug': post.slug,
                'excerpt': post.excerpt,
                'featured_image': post.featured_image,
                'is_published': post.is_published,
                'date_posted': post.date_posted.isoformat(),
                'last_modified': post.last_modified.isoformat(),
                'comment_count': len(post.comments),
                'tags': [tag.name for tag in post.tags]
            }
            output.append(post_data)
        
        # Add pagination metadata
        pagination = {
            'page': page,
            'per_page': per_page,
            'total_pages': posts.pages,
            'total_items': posts.total,
            'has_next': posts.has_next,
            'has_prev': posts.has_prev
        }
        
        return jsonify({
            'posts': output,
            'pagination': pagination
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching user posts: {str(e)}")
        return jsonify({"message": "Error fetching your posts"}), 500

# Update Post
@app.route('/posts/<int:post_id>', methods=['PUT'])
@jwt_required()
def update_post(post_id):
    if not request.is_json:
        return jsonify({"message": "Missing JSON in request"}), 400
        
    try:
        current_user_id = get_jwt_identity()
        post = Post.query.get_or_404(post_id)
        
        if post.user_id != current_user_id:
            return jsonify({"message": "You are not authorized to update this post"}), 403
            
        data = request.get_json()
        
        # Update basic fields
        if 'title' in data:
            post.title = data['title']
            post.update_slug(data['title'])  # Update slug if title changes
            
        if 'content' in data:
            post.content = data['content']
            
        if 'excerpt' in data:
            post.excerpt = data['excerpt']
            
        if 'featured_image' in data:
            post.featured_image = data['featured_image']
            
        if 'is_published' in data:
            post.is_published = bool(data['is_published'])
        
        # Handle tags if provided
        if 'tags' in data and isinstance(data['tags'], list):
            # Clear existing tags
            post.tags = []
            
            # Add new tags
            for tag_name in data['tags']:
                if not tag_name.strip():
                    continue
                    
                # Find existing tag or create new one
                tag = Tag.query.filter_by(name=tag_name.lower()).first()
                if not tag:
                    tag = Tag(name=tag_name.lower())
                    db.session.add(tag)
                post.tags.append(tag)
        
        # Update last_modified timestamp
        post.last_modified = datetime.utcnow()
        
        db.session.commit()
        
        # Prepare response
        post_data = {
            "id": post.id,
            "title": post.title,
            "slug": post.slug,
            "excerpt": post.excerpt,
            "content": post.content,
            "featured_image": post.featured_image,
            "is_published": post.is_published,
            "date_posted": post.date_posted.isoformat(),
            "last_modified": post.last_modified.isoformat(),
            "user_id": post.user_id,
            "author": post.author.username,
            "tags": [tag.name for tag in post.tags]
        }
        
        return jsonify({
            "message": "Post updated successfully",
            "post": post_data
        }), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating post: {str(e)}")
        return jsonify({"message": "Error updating post"}), 500

# Delete Post
@app.route('/posts/<int:post_id>', methods=['DELETE'])
@jwt_required()
def delete_post(post_id):
    try:
        current_user_id = get_jwt_identity()
        post = Post.query.get_or_404(post_id)
        
        if post.user_id != current_user_id:
            return jsonify({"message": "You are not authorized to delete this post"}), 403
        
        # Store post data for response before deletion
        post_data = {
            "id": post.id,
            "title": post.title,
            "slug": post.slug,
            "was_published": post.is_published
        }
        
        # Delete the post (cascade will handle related comments and tag associations)
        db.session.delete(post)
        db.session.commit()
        
        # Clean up any tags that are no longer in use
        unused_tags = Tag.query.outerjoin(post_tags).filter(Tag.id == None).all()
        for tag in unused_tags:
            db.session.delete(tag)
        db.session.commit()
        
        return jsonify({
            "message": "Post deleted successfully",
            "deleted_post": post_data
        }), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting post: {str(e)}")
        return jsonify({"message": "Error deleting post"}), 500

# Add Comment
@app.route('/posts/<int:post_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    if not request.is_json:
        return jsonify({"message": "Missing JSON in request"}), 400
        
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        if not data or not data.get('content') or not data['content'].strip():
            return jsonify({"message": "Comment content is required and cannot be empty"}), 400
            
        # Check if post exists and is published
        post = Post.query.get_or_404(post_id)
        if post.is_published is False and post.user_id != current_user_id:
            return jsonify({"message": "Cannot comment on an unpublished post"}), 403
        
        # Create and save the comment
        new_comment = Comment(
            content=data['content'].strip(),
            user_id=current_user_id,
            post_id=post.id
        )
        
        db.session.add(new_comment)
        db.session.commit()
        
        # Format the response
        comment_data = {
            "id": new_comment.id,
            "content": new_comment.content,
            "date_posted": new_comment.date_posted.isoformat(),
            "author": {
                "id": new_comment.comment_author.id,
                "username": new_comment.comment_author.username
            },
            "post": {
                "id": post.id,
                "title": post.title,
                "slug": post.slug
            }
        }
        
        return jsonify({
            "message": "Comment added successfully",
            "comment": comment_data
        }), 201
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding comment: {str(e)}")
        return jsonify({"message": "Error adding comment"}), 500

# Get Comments for Post
@app.route('/posts/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    try:
        # Check if post exists
        post = Post.query.get_or_404(post_id)
        
        # Check post visibility
        current_user_id = get_jwt_identity() if 'Authorization' in request.headers else None
        if post.is_published is False and (not current_user_id or current_user_id != post.user_id):
            return jsonify({"message": "Post not found"}), 404
        
        # Pagination
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        # Sorting
        sort_order = request.args.get('sort', 'desc').lower()
        sort_field = request.args.get('sort_by', 'date_posted').lower()
        
        # Validate sort parameters
        valid_sort_fields = {'id', 'date_posted'}
        if sort_field not in valid_sort_fields:
            sort_field = 'date_posted'
            
        sort_direction = db.desc if sort_order == 'desc' else db.asc
        
        # Base query
        query = Comment.query.filter_by(post_id=post_id)
        
        # Apply sorting
        if sort_field == 'date_posted':
            query = query.order_by(sort_direction(Comment.date_posted))
        else:
            query = query.order_by(sort_direction(Comment.id))
        
        # Apply pagination
        comments = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        output = []
        for comment in comments.items:
            output.append({
                'id': comment.id,
                'content': comment.content,
                'date_posted': comment.date_posted.isoformat(),
                'author': {
                    'id': comment.comment_author.id,
                    'username': comment.comment_author.username
                }
            })
        
        # Add pagination metadata
        pagination = {
            'page': page,
            'per_page': per_page,
            'total_pages': comments.pages,
            'total_items': comments.total,
            'has_next': comments.has_next,
            'has_prev': comments.has_prev
        }
        
        return jsonify({
            'comments': output,
            'pagination': pagination,
            'post': {
                'id': post.id,
                'title': post.title,
                'slug': post.slug,
                'comment_count': len(post.comments)
            }
        }), 200
        
    except Exception as e:
        app.logger.error(f"Error fetching comments: {str(e)}")
        return jsonify({"message": "Error fetching comments"}), 500
